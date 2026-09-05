"""v1.0.0 fix-round tests — three critical behaviours:

  1. AI Assistant grounding (the "I cannot ground this in corpus evidence"
     dead-end): the system prompt must guide tool use instead of scripted
     refusal; auto-grounding must plan the right tools for a message;
     the live corpus snapshot must be injected and cached.

  2. Collocation network API (engine/api/network.py): delta_p mapping,
     graph assembly with depth-2 meshing, expansion with known_nodes.

  3. Cloud provider config: gemini/custom literals, Gemini default model,
     Gemini default base URL, custom-provider Base URL requirement.

No LLM, no Ollama, no network. Uses a file-based SQLite DB (execute_tool
opens its own session_scope, exactly like production).
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

_DB_FILE = "/tmp/cm-test-v100-fixes.db"
if os.path.exists(_DB_FILE):
    os.remove(_DB_FILE)
os.environ["CORPUSMIND_DB_URL"] = f"sqlite+aiosqlite:///{_DB_FILE}"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data-v100fixes"

import pytest  # noqa: E402 — env must be set first
from pydantic import ValidationError  # noqa: E402

# Make the engine importable.
ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))


# --------------------------------------------------------------------------- #
# 1a. Assistant system prompt
# --------------------------------------------------------------------------- #


def _base_prompt_text() -> str:
    from ai.assistant import Assistant

    # The prompt body is assembled in __init__; the static part lives in a
    # module/class constant. Reconstruct it without an LLM call.
    a = object.__new__(Assistant)
    return getattr(type(a), "SYSTEM_PROMPT", "") or getattr(a, "system_prompt", "")


def test_assistant_prompt_prompts_tool_use_not_refusal():
    """The prompt must direct the model to CALL TOOLS, and must no longer
    teach the model to answer with the canned refusal line."""
    import ai.assistant as assistant_mod

    prompt_source = "\n".join(
        c for c in (
            getattr(assistant_mod, "_SYSTEM_PROMPT", None),
            getattr(assistant_mod.Assistant, "SYSTEM_PROMPT", None),
        ) if isinstance(c, str)
    )
    # Fall back to scanning the module source for the prompt literals if the
    # constant is named differently — the behaviour is what matters.
    if not prompt_source:
        src = Path(assistant_mod.__file__).read_text(encoding="utf-8")
        prompt_source = src

    assert "CALL A TOOL" in prompt_source, "prompt must tell the model to call tools"
    assert "get_corpus_overview" in prompt_source, "prompt must name at least one tool"
    assert (
        "I cannot ground this in corpus evidence" not in prompt_source
    ), "canned refusal must be gone from the prompt (auto-grounding replaces it)"


def test_salient_terms_quoted_span_wins():
    from ai.assistant import _salient_terms

    assert _salient_terms("What does 'elephant' collocate with?") == ["elephant"]
    terms = _salient_terms("show me examples of migration in the corpus")
    assert "migration" in terms
    assert all(t not in ("the", "of", "in", "show", "me") for t in terms)


def test_plan_auto_tools_intents():
    from ai.assistant import _plan_auto_tools

    plans = _plan_auto_tools("what collocates with 'government'?")
    assert plans[0][0] == "compute_collocations"
    assert plans[0][1]["node"] == "government"

    plans = _plan_auto_tools("what are the most frequent words?")
    assert any(name == "get_frequency" for name, _ in plans)

    plans = _plan_auto_tools("show concordance lines for 'climate'")
    assert any(name == "search_concordance" for name, _ in plans)

    # Fallback: empirical-sounding message with no matched intent still
    # gets grounded data (overview + frequency) instead of a refusal.
    plans = _plan_auto_tools("tell me something interesting about this corpus")
    assert any(name == "get_corpus_overview" for name, _ in plans)
    assert any(name == "get_frequency" for name, _ in plans)


def test_plan_auto_tools_never_suggests_keyness():
    """keyness needs a reference corpus — it must never be auto-planned."""
    from ai.assistant import _plan_auto_tools

    for msg in (
        "keyness of 'freedom' versus the reference corpus",
        "compare frequencies with the reference corpus",
        "what is distinctive about this corpus?",
    ):
        plans = _plan_auto_tools(msg)
        assert all(name != "keyness" for name, _ in plans), msg


# --------------------------------------------------------------------------- #
# 1b. Live corpus snapshot (DB-backed)
# --------------------------------------------------------------------------- #


@pytest.fixture()
def seeded_db():
    """Initialize DB + one tiny corpus with a document, return corpus id."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_setup_db())
        cid = loop.run_until_complete(_seed_corpus())
        yield cid
        from storage.session import dispose_db

        loop.run_until_complete(dispose_db())
    finally:
        loop.close()


async def _setup_db():
    from storage.session import init_db

    await init_db()


async def _seed_corpus() -> str:
    from storage.models import Corpus, Document, Project
    from storage.session import session_scope

    async with session_scope() as s:
        pid = uuid.uuid4().hex[:16]
        cid = uuid.uuid4().hex[:16]
        s.add(Project(id=pid, name="P-v100", language="en"))
        s.add(Corpus(id=cid, project_id=pid, name="Snapshot corpus", language="en"))
        s.add(Document(id=uuid.uuid4().hex[:16], corpus_id=cid, filename="doc.txt"))
    return cid


def test_corpus_snapshot_returns_data_and_caches(seeded_db):
    from ai.assistant import _corpus_snapshot, _snapshot_cache

    cid = seeded_db

    async def run():
        # fresh cache
        _snapshot_cache.pop(cid, None)
        first = await _corpus_snapshot(cid)
        second = await _corpus_snapshot(cid)
        return first, second

    loop = asyncio.new_event_loop()
    try:
        first, second = loop.run_until_complete(run())
    finally:
        loop.close()

    assert first != "", "snapshot must produce data for a real corpus"
    assert len(first) <= 1500, "snapshot must stay compact"
    assert second == first, "second call must hit the cache"


def test_corpus_snapshot_bad_corpus_is_empty_string():
    from ai.assistant import _corpus_snapshot, _snapshot_cache

    loop = asyncio.new_event_loop()
    try:
        out = loop.run_until_complete(_corpus_snapshot("nope-does-not-exist"))
    finally:
        loop.close()
    assert out == "", "unknown corpus must yield an empty snapshot, not an error"
    assert "nope-does-not-exist" not in _snapshot_cache


# --------------------------------------------------------------------------- #
# 2. Collocation network
# --------------------------------------------------------------------------- #


def _row(collocate: str, o: int = 5, fx: int = 20, fy: int = 15, **measures):
    base = {"collocate": collocate, "O": o, "fx": fx, "fy": fy, "N": 1000}
    base.update(measures)
    return base


class _FakeResult:
    def __init__(self, rows):
        self.rows = rows


def _patch_compute(monkeypatch, table: dict[str, list[dict]]):
    """Patch api.network.compute_collocations with a canned table."""
    import api.network as network_mod

    async def fake_compute(session, corpus_id, pivot, **kwargs):
        return _FakeResult(table.get(pivot, []))

    monkeypatch.setattr(network_mod, "compute_collocations", fake_compute)


def test_row_measure_maps_delta_p():
    from api.network import _row_measure

    row = _row("x", delta_p_y_given_x=0.31, delta_p_x_given_y=0.02)
    assert _row_measure(row, "delta_p") == pytest.approx(0.31)
    assert _row_measure(row, "mi") == pytest.approx(0.0)
    row_bad = _row("y", mi="not-a-number")
    assert _row_measure(row_bad, "mi") == 0.0


def test_network_build_depth2_meshes(monkeypatch):
    from api.network import NetworkRequest, collocation_network

    table = {
        "deep": [
            _row("ocean", mi=3.1, delta_p_y_given_x=0.2),
            _row("blue", mi=2.5, delta_p_y_given_x=0.1),
        ],
        "ocean": [_row("blue", mi=1.9), _row("deep", mi=3.1)],
        "blue": [_row("ocean", mi=1.9)],
    }
    _patch_compute(monkeypatch, table)

    req = NetworkRequest(node="deep", level="word", window=5, min_freq=1, measure="mi", depth=2)
    loop = asyncio.new_event_loop()
    try:
        out = loop.run_until_complete(collocation_network("cid", req, session=None))
    finally:
        loop.close()

    node_ids = {n["id"] for n in out["nodes"]}
    assert {"deep", "ocean", "blue"} <= node_ids
    # depth-2 meshing must add the ocean–blue edge beyond the two spokes.
    pairs = {frozenset((e["source"], e["target"])) for e in out["edges"]}
    assert frozenset(("ocean", "blue")) in pairs
    assert out["stats"]["edges"] == 3
    # Every edge echoes the measure keys for frontend re-weighting.
    for e in out["edges"]:
        assert "mi" in e and "weight" in e


def test_network_build_delta_p_measure(monkeypatch):
    """Choosing delta_p must produce NONZERO weights (x→y mapping)."""
    from api.network import NetworkRequest, collocation_network

    table = {
        "state": [_row("power", mi=1.0, delta_p_y_given_x=0.45)],
    }
    _patch_compute(monkeypatch, table)

    req = NetworkRequest(node="state", level="word", window=5, min_freq=1, measure="delta_p", depth=1)
    loop = asyncio.new_event_loop()
    try:
        out = loop.run_until_complete(collocation_network("cid", req, session=None))
    finally:
        loop.close()

    assert out["edges"][0]["weight"] == pytest.approx(0.45)
    assert out["edges"][0]["delta_p"] == pytest.approx(0.45)


def test_network_expand_excludes_known(monkeypatch):
    from api.network import ExpandRequest, collocation_network_expand

    table = {
        "node": [
            _row("old-friend", mi=3.0),   # already in the graph
            _row("new-a", mi=2.5),
            _row("new-b", mi=2.0),
        ],
        "new-a": [_row("node", mi=2.5)],
    }
    _patch_compute(monkeypatch, table)

    req = ExpandRequest(
        node="node", level="word", window=5, min_freq=1,
        measure="mi", top_n=5, depth=2,
        known_nodes=["old-friend"],
    )
    loop = asyncio.new_event_loop()
    try:
        out = loop.run_until_complete(collocation_network_expand("cid", req, session=None))
    finally:
        loop.close()

    assert "old-friend" not in out["new_nodes"]
    assert {"new-a", "new-b"} <= set(out["new_nodes"])
    # the new-a—node edge must still be attached server-side
    pairs = {frozenset((e["source"], e["target"])) for e in out["edges"]}
    assert frozenset(("node", "new-a")) in pairs


def test_network_empty_result_shape(monkeypatch):
    from api.network import NetworkRequest, collocation_network

    _patch_compute(monkeypatch, {"lonely": []})
    req = NetworkRequest(node="lonely", level="word", window=5, min_freq=1)
    loop = asyncio.new_event_loop()
    try:
        out = loop.run_until_complete(collocation_network("cid", req, session=None))
    finally:
        loop.close()
    assert out["nodes"] == [] and out["edges"] == []
    assert out["stats"]["nodes"] == 0


# --------------------------------------------------------------------------- #
# 3. Cloud provider config (Gemini + custom)
# --------------------------------------------------------------------------- #


def test_cloud_config_request_accepts_gemini_and_custom():
    from api.ai_provider_config import CloudConfigRequest

    for provider in ("gemini", "custom", "openai", "anthropic"):
        req = CloudConfigRequest(  # noqa: F841
            provider=provider, api_key="k" * 8, acknowledge_data_leaves_device=True
        )
    with pytest.raises(ValidationError):
        CloudConfigRequest(
            provider="deepseek-native", api_key="k" * 8, acknowledge_data_leaves_device=True
        )


def test_cloud_provider_gemini_defaults():
    from ai.providers import CloudProvider
    from app.settings import Settings

    s = Settings(
        cloud_provider="gemini",
        cloud_api_key="test-key",
        corpusmind_data_dir="/tmp/cm-gemini-test",
    )
    p = CloudProvider(s)
    assert p.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert p.default_model == "gemini-2.5-flash"
    assert p.auth_header == "Bearer test-key"


def test_cloud_provider_custom_requires_base_url():
    from ai.providers import CloudDisabledError, CloudProvider
    from app.settings import Settings

    s = Settings(
        cloud_provider="custom",
        cloud_api_key="test-key",
        corpusmind_data_dir="/tmp/cm-custom-test",
    )
    with pytest.raises(CloudDisabledError, match="Base URL"):
        CloudProvider(s)

    s2 = Settings(
        cloud_provider="custom",
        cloud_api_key="test-key",
        cloud_base_url="https://api.deepseek.com/v1",
        corpusmind_data_dir="/tmp/cm-custom-test2",
    )
    p2 = CloudProvider(s2)
    assert p2.base_url == "https://api.deepseek.com/v1"


def test_settings_literal_accepts_new_providers():
    from app.settings import Settings

    s = Settings(cloud_provider="gemini", corpusmind_data_dir="/tmp/cm-lit1")
    assert s.cloud_provider == "gemini"
    s2 = Settings(cloud_provider="custom", corpusmind_data_dir="/tmp/cm-lit2")
    assert s2.cloud_provider == "custom"
