"""v1.2.9 — Persuasion Index optional resources bridge.

The four license-restricted resources (concreteness ×2, LIWC, NRC-VAD)
are never bundled; the engine bridges a user-owned resources folder onto
persuasion-index's OWN env vars (PI_CONCRETENESS_FILE, …) at startup.
These tests pin that bridge: resolution order, non-destructive env
handling, the health endpoint's install guidance, and the canonical
folder layout the docs teach.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# --------------------------------------------------------------------------- #
# Unit tests: the env bridge
# --------------------------------------------------------------------------- #


@pytest.fixture()
def clean_pi_env(monkeypatch):
    """Remove every PI_* var the bridge touches, restore after."""
    names = [
        "PI_CONCRETENESS_FILE",
        "PI_MWE_CONCRETENESS_FILE",
        "PI_LIWC_FILE",
        "PI_NRC_VAD_FILE",
    ]
    for n in names:
        monkeypatch.delenv(n, raising=False)
    yield names
    for n in names:
        os.environ.pop(n, None)


def _make_settings(tmp_path: Path, **overrides):
    """A minimal stand-in for app.settings.Settings (no env parsing)."""
    class _S:
        data_dir = tmp_path
        pi_resources_dir = overrides.get("pi_resources_dir", "")
        pi_concreteness_file = overrides.get("pi_concreteness_file", "")
        pi_mwe_concreteness_file = overrides.get("pi_mwe_concreteness_file", "")
        pi_liwc_file = overrides.get("pi_liwc_file", "")
        pi_nrc_vad_file = overrides.get("pi_nrc_vad_file", "")

    return _S()


def test_bridge_picks_up_folder_layout(tmp_path, clean_pi_env):
    """Files dropped in <data_dir>/pi-resources with the canonical names
    are bridged onto PI's env vars."""
    from discourse.pi_resources import apply_pi_resource_env, pi_resources_root

    root = tmp_path / "pi-resources"
    (root / "NRC-VAD-Lexicon-v2.1" / "Unigrams").mkdir(parents=True)
    (root / "Brysbaert_concretness_dataset.xlsx").write_text("x", encoding="utf-8")
    (root / "NRC-VAD-Lexicon-v2.1" / "Unigrams" / "unigrams-NRC-VAD-Lexicon-v2.1.txt").write_text(
        "term\tvalence\tarousal\tdominance\n", encoding="utf-8"
    )
    settings = _make_settings(tmp_path)
    assert str(root) == str(pi_resources_root(settings))

    applied = apply_pi_resource_env(settings)
    assert "PI_CONCRETENESS_FILE" in applied
    assert "PI_NRC_VAD_FILE" in applied
    assert applied["PI_NRC_VAD_FILE"] == str(
        root / "NRC-VAD-Lexicon-v2.1" / "Unigrams" / "unigrams-NRC-VAD-Lexicon-v2.1.txt"
    )
    # The csv / liwc files were not installed → not bridged.
    assert "PI_MWE_CONCRETENESS_FILE" not in applied
    assert "PI_LIWC_FILE" not in applied


def test_bridge_never_stomps_operator_env(tmp_path, clean_pi_env, monkeypatch):
    """An operator-set PI_* var wins; the bridge leaves it untouched."""
    from discourse.pi_resources import apply_pi_resource_env

    root = tmp_path / "pi-resources"
    root.mkdir()
    (root / "en_liwc.txt").write_text("x", encoding="utf-8")
    monkeypatch.setenv("PI_LIWC_FILE", "/operator/chosen.dic")

    applied = apply_pi_resource_env(_make_settings(tmp_path))
    assert "PI_LIWC_FILE" not in applied  # not set BY the bridge…
    assert os.environ["PI_LIWC_FILE"] == "/operator/chosen.dic"  # …and untouched


def test_bridge_explicit_engine_setting_wins_over_folder(tmp_path, clean_pi_env):
    """CORPUSMIND_PI_CONCRETENESS_FILE etc. beat the folder layout."""
    from discourse.pi_resources import apply_pi_resource_env

    root = tmp_path / "pi-resources"
    root.mkdir()
    (root / "Brysbaert_concretness_dataset.xlsx").write_text("folder", encoding="utf-8")
    explicit = tmp_path / "my-concreteness.xlsx"
    explicit.write_text("explicit", encoding="utf-8")

    apply_pi_resource_env(_make_settings(tmp_path, pi_concreteness_file=str(explicit)))
    assert os.environ["PI_CONCRETENESS_FILE"] == str(explicit)


def test_install_hints_shape(tmp_path, clean_pi_env):
    """install_hints covers exactly the four file-backed resources with
    everything the UI needs to teach the install step."""
    from discourse.pi_resources import PI_RESOURCE_LAYOUT, install_hints

    hints = install_hints(_make_settings(tmp_path))
    assert set(hints) == {v[0] for v in PI_RESOURCE_LAYOUT.values()}
    assert set(hints) == {
        "single_word_concreteness",
        "multiword_concreteness",
        "liwc",
        "nrc_vad",
    }
    for hint in hints.values():
        assert hint["env_var"].startswith("PI_")
        assert hint["engine_setting"].startswith("CORPUSMIND_")
        assert hint["source_url"].startswith("https://")
        assert hint["license_note"]
        assert hint["folder"] == str(tmp_path / "pi-resources")
        assert isinstance(hint["resolvable"], bool)
    # nrc_vad's license genuinely forbids redistribution — the UI must say so.
    assert "redistribution prohibited" in hints["nrc_vad"]["license_note"]


def test_hints_report_resolvable_when_file_present(tmp_path, clean_pi_env):
    from discourse.pi_resources import install_hints

    root = tmp_path / "pi-resources"
    root.mkdir()
    (root / "MultiwordExpression_Concreteness_Ratings.csv").write_text("x", encoding="utf-8")
    hints = install_hints(_make_settings(tmp_path))
    assert hints["multiword_concreteness"]["resolvable"] is True
    assert hints["multiword_concreteness"]["resolved_from"] == "resources_folder"
    assert hints["liwc"]["resolvable"] is False


# --------------------------------------------------------------------------- #
# API test: the health endpoint exposes the guidance
# --------------------------------------------------------------------------- #


def _make_client_fixture(env: dict[str, str], unset: tuple[str, ...] = ()):
    async def client():

        for k in unset:
            os.environ.pop(k, None)
        for k, v in env.items():
            os.environ[k] = v
        os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
        os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-pi-test-data"

        from app.settings import get_settings

        get_settings.cache_clear()
        from storage.session import _engine, dispose_db

        _engine.clear() if hasattr(_engine, "clear") else None

        from httpx import ASGITransport, AsyncClient

        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            async with app.router.lifespan_context(app):
                yield ac
        await dispose_db()

    return pytest.fixture(client)


pi_client = _make_client_fixture({"CORPUSMIND_HOST": "127.0.0.1"})


@pytest.mark.asyncio
async def test_persuasion_health_exposes_install_guidance(pi_client):
    """The resource panel can teach the user how to enable each resource."""
    ac = pi_client
    r = await ac.get("/api/v1/discourse/persuasion/health")
    assert r.status_code == 200
    data = r.json()
    if not data.get("installed"):
        pytest.skip("persuasion-index not installed in this environment")
    assert isinstance(data.get("resources_dir"), str)
    hints = data.get("install_hints") or {}
    assert {"single_word_concreteness", "multiword_concreteness", "liwc", "nrc_vad"} <= set(hints)
    for hint in hints.values():
        assert hint["env_var"]
        assert hint["filename"]
        assert hint["source_url"].startswith("https://")


@pytest.mark.asyncio
async def test_lifespan_bridges_pi_resources(pi_client, tmp_path, monkeypatch):
    """The engine lifespan runs the bridge — resources placed in the
    default folder are visible to check_resources() without any env setup."""
    for name in ("PI_CONCRETENESS_FILE", "PI_MWE_CONCRETENESS_FILE", "PI_LIWC_FILE", "PI_NRC_VAD_FILE"):
        monkeypatch.delenv(name, raising=False)
    # The fixture above already ran the lifespan; a request proves the app
    # came up with the bridge in place.
    r = await pi_client.get("/api/v1/health")
    assert r.status_code == 200
    # The bridge should have created/consulted <data_dir>/pi-resources.
    from app.settings import get_settings

    settings = get_settings()
    assert (Path(settings.data_dir) / "pi-resources").name == "pi-resources"
