"""Offline tests for the evaluation harness (eval package).

Covers: snapshot integrity, bank validation, the scorer's number extraction
and verdict classification (incl. Arabic-Indic digits, line-id exclusion,
percent/fraction equivalence, trap handling), the frozen gold's internal
consistency, a live gold-subset rebuild against the committed gold (stop on
disagreement), an end-to-end grounding run through the real chat endpoint
with a scripted stub provider, and the AraSEG boundary metrics on synthetic
documents.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from eval.build_gold import boot_engine
from eval.corpus_snapshot import verify_snapshot
from eval.questions import QUESTION_BANK, validate_bank

_GOLD = Path(__file__).resolve().parents[1] / "eval" / "data" / "gold" / "grounding_gold.json"


# --------------------------------------------------------------------- #
# fixture integrity
# --------------------------------------------------------------------- #
def test_snapshot_integrity() -> None:
    docs = verify_snapshot()
    assert len(docs) == 9
    assert all(d.sha256 for d in docs)


def test_bank_valid() -> None:
    assert len(QUESTION_BANK) == 80
    assert validate_bank() == []


def test_frozen_gold_consistent_with_snapshot() -> None:
    if not _GOLD.exists():  # gold is committed; guard for exotic checkouts
        pytest.skip("grounding gold not present")
    gold = json.loads(_GOLD.read_text(encoding="utf-8"))
    assert gold["_meta"]["question_count"] == 80
    assert len(gold["questions"]) == 80
    manifest = {d.file: d.sha256 for d in verify_snapshot()}
    assert gold["_meta"]["snapshot"] == manifest
    for q in gold["questions"]:
        assert "gold" in q, f"{q['id']} has no resolved gold"


# --------------------------------------------------------------------- #
# scorer units
# --------------------------------------------------------------------- #
def test_extract_numbers_normalizes_arabic_digits_and_skips_ids() -> None:
    from eval.score import extract_numbers

    assert extract_numbers("هناك ٣٥ كلمة و 7 جمل") == [35.0, 7.0]
    # line ids and hex doc ids and versions are not statistics
    assert extract_numbers("see line a1b2c3d4:1:2 and doc 9f8e7d6c and v2.0.0") == []
    assert extract_numbers("3.4 million, 25%, -2") == [3.4, 25.0, -2.0]


def test_matches_tolerance_and_percent_equivalence() -> None:
    from eval.score import _matches

    assert _matches(384.0, 384.0, 0)          # exact count
    assert _matches(0.074, 0.0744, 1e-6)      # 0.5% float tolerance
    assert not _matches(0.5, 0.744, 1e-6)
    assert _matches(74.4, 0.744, 0)           # percent form of a fraction
    assert _matches(75.0, 0.75, 1e-6)         # percent equivalence (tolerant)
    assert not _matches(383.0, 384.0, 0)      # wrong count stays wrong


def _mini_gold(kind: str) -> dict[str, Any]:
    tools = [{"name": "search_concordance", "args": {}, "ok": True,
              "result": {"total_matches": 0, "lines": [], "query": {"window": 3}}}]
    if kind == "present_row":
        tools = [{"name": "compute_keyness", "args": {}, "ok": True,
                  "result": {"positive_keywords": [{"term": "my", "log_ratio": 1.2}]}}]
    return {
        "id": "T-1", "category": "trap", "language": "en", "corpus": "C1",
        "tools": tools,
        "gold": {"numbers": [], "strings": [], "traps": {"zero": True} if kind == "zero" else
                 ({"no_tool": True} if kind == "no_tool" else
                  ({"error": True} if kind == "error" else
                   ({"absent": ["row"]} if kind == "absent" else {"present": ["row"]})))},
    }


def _score_with(kind: str, answer: str, trap: bool = False) -> dict[str, Any]:
    from eval.score import score_question

    q = _mini_gold(kind)
    q["trap"] = trap
    if kind == "zero":
        q["gold"]["numbers"] = [{"label": "total hits", "value": 0, "tol": 0}]
    return score_question(q, {"id": "T-1", "answer": answer})


def test_zero_trap_honest_pass_and_invention_fail() -> None:
    ok = _score_with("zero", "The word does not occur at all — 0 hits in this corpus.", trap=True)
    assert ok["verdict"] == "PASS"
    bad = _score_with("zero", "I found 3 hits for that word.", trap=True)
    assert bad["verdict"] in ("TRAP_FAILURE", "HALLUCINATED")
    assert any("absence" in n or "not in any tool" in n for n in bad["detail"]["notes"])


def test_no_tool_trap() -> None:
    ok = _score_with("no_tool", "The engine does not expose that measure; I cannot ground it.")
    assert ok["verdict"] == "PASS"
    bad = _score_with("no_tool", "Sure — the value is 0.83 for this corpus.")
    assert bad["verdict"] == "TRAP_FAILURE"


def test_error_trap_acknowledgement() -> None:
    q = _mini_gold("error")
    q["tools"] = [{"name": "search_cql", "args": {}, "ok": False, "error": "syntax error at pos 1"}]
    from eval.score import score_question

    ok = score_question(q, {"id": "T-1", "answer": "The query failed — invalid CQL syntax."})
    assert ok["verdict"] == "PASS"
    bad = score_question(q, {"id": "T-1", "answer": "The query returns 5 hits."})
    assert bad["verdict"] == "TRAP_FAILURE"


def test_absent_and_present_markers() -> None:
    ok = _score_with("absent", "'the' is not listed among the positive keywords.")
    assert ok["verdict"] == "PASS"
    bad = _score_with("absent", "'the' has a log ratio of 2.5.")
    assert bad["verdict"] == "TRAP_FAILURE"
    ok2 = _score_with("present_row", "Yes — 'my' is among the positive keywords.")
    assert ok2["verdict"] == "PASS"


def test_missing_and_hallucinated_numbers() -> None:
    from eval.score import score_question

    q = {
        "id": "T-2", "category": "corpus_stats", "language": "en", "corpus": "C1",
        "tools": [{"name": "get_corpus_overview", "args": {}, "ok": True,
                   "result": {"text_side": {"token_count": 384, "type_count": 257}}}],
        "gold": {"numbers": [{"label": "tokens", "value": 384.0, "tol": 0},
                             {"label": "types", "value": 257.0, "tol": 0}],
                 "strings": [], "traps": {}},
        "trap": False,
    }
    perfect = score_question(q, {"id": "T-2", "answer": "384 tokens and 257 types."})
    assert perfect["verdict"] == "PASS"
    missing = score_question(q, {"id": "T-2", "answer": "384 tokens."})
    assert missing["verdict"] == "MISSING_NUMBER"
    halluc = score_question(q, {"id": "T-2", "answer": "384 tokens, 257 types, 91 sentences."})
    assert halluc["verdict"] == "HALLUCINATED"


# --------------------------------------------------------------------- #
# live rebuild subset vs committed gold (stop-on-disagreement)
# --------------------------------------------------------------------- #
def test_gold_rebuild_subset_matches_frozen() -> None:
    if not _GOLD.exists():
        pytest.skip("grounding gold not present")
    frozen = {q["id"]: q for q in json.loads(_GOLD.read_text(encoding="utf-8"))["questions"]}
    from eval.build_gold import build

    doc = _run(build(["G-001", "G-003"]))
    fresh = {q["id"]: q for q in doc["questions"]}
    for qid in ("G-001", "G-003"):
        assert fresh[qid]["gold"] == frozen[qid]["gold"], (
            f"{qid}: rebuilt gold disagrees with the frozen gold — "
            "the engine output changed; review before regenerating"
        )


def _run(coro: Any) -> Any:  # tiny helper: run a coroutine to completion
    import asyncio

    return asyncio.run(coro)


# --------------------------------------------------------------------- #
# end-to-end grounding through the real chat endpoint (stub provider)
# --------------------------------------------------------------------- #
class _ScriptedProvider:
    """Round 1: emit the gold question's first tool call; round 2: answer
    with the frozen gold numbers verbatim (or a corrupted variant)."""

    name = "stub"
    default_model = "stub-model"

    def __init__(self, q: dict[str, Any], corrupt: bool) -> None:
        self.q = q
        self.corrupt = corrupt

    async def health(self) -> bool:
        return True

    async def pick_default_model(self) -> str | None:
        return self.default_model

    async def supports_tools(self, model: str | None = None) -> bool:
        return True

    async def list_models(self) -> list[str]:
        return [self.default_model]

    async def chat(self, messages: Any, model: Any = None, temperature: float = 0.2, tools: Any = None, timeout: float | None = None) -> Any:
        from ai.providers import ChatResponse

        if any(m.role == "tool" for m in messages):
            if self.corrupt:
                return ChatResponse(content="I found 91 hits for that query.",
                                    model=model or self.default_model, provider=self.name, raw={})
            parts = []
            for n in self.q["gold"]["numbers"]:
                v = n["value"]
                if isinstance(v, list):
                    parts.append(", ".join(str(x) for x in v))
                elif float(v).is_integer():
                    parts.append(str(int(v)))
                else:
                    parts.append(str(v))
            for s in self.q["gold"]["strings"]:
                parts.append(str(s["value"]))
            return ChatResponse(content="The tool reports: " + ", ".join(parts) + ".",
                                model=model or self.default_model, provider=self.name, raw={})
        tool = self.q["tools"][0]
        args = dict(tool["args"])
        return ChatResponse(
            content="", model=model or self.default_model, provider=self.name,
            raw={"choices": [{"message": {"tool_calls": [
                {"function": {"name": tool["name"], "arguments": json.dumps(args)}}
            ]}}]},
        )


class _StubRegistry:
    def __init__(self, provider: _ScriptedProvider) -> None:
        self._provider = provider

    def get(self, name: str | None = None) -> Any:
        return self._provider


async def _chat_one(q: dict[str, Any], corrupt: bool) -> dict[str, Any]:
    from app.main import app
    from eval.corpus_snapshot import prepare_corpora
    from eval.questions import QUESTION_BANK

    gold_q = next(x for x in QUESTION_BANK if x["id"] == q["id"])
    async with boot_engine() as client:
        corpus_map = await prepare_corpora(client)
        app.state.providers = _StubRegistry(_ScriptedProvider(q, corrupt))
        r = await client.post("/api/v1/ai/chat", json={
            "message": gold_q["question"],
            "corpus_id": corpus_map[gold_q["corpus"]],
            "provider": "stub",
        })
        assert r.status_code == 200, r.text[:300]
        return {"id": q["id"], "answer": r.json().get("content", "")}


def test_end_to_end_grounded_answer_scores_pass() -> None:
    if not _GOLD.exists():
        pytest.skip("grounding gold not present")
    gold = json.loads(_GOLD.read_text(encoding="utf-8"))
    q58 = next(q for q in gold["questions"] if q["id"] == "G-058")  # stateless tool
    from eval.score import score_question

    run = _run(_chat_one(q58, corrupt=False))
    verdict = score_question(q58, run)
    assert verdict["verdict"] == "PASS", verdict


def test_end_to_end_hallucinated_answer_is_caught() -> None:
    if not _GOLD.exists():
        pytest.skip("grounding gold not present")
    gold = json.loads(_GOLD.read_text(encoding="utf-8"))
    q58 = next(q for q in gold["questions"] if q["id"] == "G-058")
    from eval.score import score_question

    run = _run(_chat_one(q58, corrupt=True))
    verdict = score_question(q58, run)
    assert verdict["verdict"] == "HALLUCINATED", verdict


# --------------------------------------------------------------------- #
# AraSEG boundary metrics on synthetic documents
# --------------------------------------------------------------------- #
def test_segmentation_predict_boundaries_newline_markers() -> None:
    """Regression: AraSEG PA streams contain bare '\\n' marker tokens; the
    predictor must map boundaries through a char-to-token owner map, not by
    re-counting whitespace tokens (which shifts every boundary after the
    first marker and produced micro-F1 0.107 on PA in run 40913999140)."""
    from eval.segmentation_araseg import predict_boundaries

    # single marker between two punctuated sentences
    toks = ["قال.", "\n", "ذهب."]
    assert predict_boundaries(toks) == [1, 0, 1]

    # cumulative case: two markers — the old counting shifted by +1 each
    toks = ["أ.", "\n", "ب.", "\n", "ج."]
    assert predict_boundaries(toks) == [1, 0, 1, 0, 1]

    # paragraph break with NO terminal punctuation: the newline itself is the
    # cue, and gold (PA: 100% of markers) puts the boundary on the content
    # token before the marker
    toks = ["أ", "ب", "\n", "ج."]
    assert predict_boundaries(toks) == [0, 1, 0, 1]

    # marker-only padding never becomes a predicted boundary
    toks = ["قال.", "\n"]
    assert predict_boundaries(toks) == [1, 0]


def test_segmentation_prf1_perfect_and_imperfect() -> None:
    from eval.segmentation_araseg import evaluate

    docs = [
        # perfect: "ق. ر س." -> chunks ["ق.", "ر س."] -> bits 1,0,1
        {"doc_id": "d1", "tokens": ["ق.", "ر", "س."], "labels": [1, 0, 1]},
        # gold wants a boundary mid-text that a punctuation splitter cannot see
        {"doc_id": "d2", "tokens": ["أ", "ب", "ج"], "labels": [0, 1, 0]},
    ]
    report = evaluate(docs)
    assert report["documents"] == 2
    assert report["per_doc"][0]["f1"] == 1.0
    assert report["per_doc"][1]["recall"] == 0.0
    assert 0.0 < report["macro_F1"] < 1.0
    assert report["micro_tp"] == 2


def test_segmentation_downstream_synthetic(tmp_path: Path) -> None:
    """Full downstream-delta path on a tiny synthetic AraSEG file; skipped
    where the Arabic data pack is unavailable (CI) — the module needs real
    Arabic ingest."""

    from eval.segmentation_downstream import run as downstream_run

    data = tmp_path / "synthetic.jsonl"
    doc = {
        "doc_id": "syn1",
        "tokens": ["ذهب", "الولد", "إلى", "المدرسة.", "وقرأ", "كتاباً", "ممتعاً", "جداً."],
        "labels": [0, 0, 0, 1, 0, 0, 0, 1],
    }
    data.write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")

    async def _probe() -> bool:
        async with boot_engine() as client:
            r = await client.post("/api/v1/arabic/analyze",
                                  json={"text": "كتب الكتاب", "dialect": "msa"})
            return bool(r.status_code == 200)

    if not _run(_probe()):
        pytest.skip("Arabic morphology pack not installed on this machine")
    report = _run(downstream_run(data, 1, None, None))
    assert report["documents"] == 1
    pair = report["pairs"][0]
    assert "delta_sentences" in pair
    # gold segmentation = 2 sentences; engine splits the same way here
    assert pair["sentences"]["gold"] == 2
