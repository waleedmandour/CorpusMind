"""Score a grounding run against the frozen gold.

Reads the gold file (eval/data/gold/grounding_gold.json) and a run file
produced by eval/run_grounding.py, extracts every number the assistant
quoted, and classifies each question:

    PASS              every gold number/string matched; trap handled honestly
    MISSING_NUMBER    a gold number was not quoted (or quoted outside tolerance)
    HALLUCINATED      a quoted number appears in NO tool output for that question
    TRAP_FAILURE      a zero-match/error/no-tool trap was answered with numbers
    NO_ANSWER         empty or unusable answer text

CLI (from engine/):
    python -m eval.score <run.json> [--gold PATH] [--out report.json] [--verbose]

Usage note: a number is *grounded* when it matches a gold value within
tolerance (exact for integer counts, 0.5% relative for floats, with
percent/fraction equivalence), and *allowed* when it appears anywhere in the
question's frozen tool outputs (the assistant may legitimately quote tool
numbers that are not part of the gold spec, e.g. context). Anything else is
hallucinated. Arabic-Indic digits are normalized before matching.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

_DEFAULT_GOLD = Path(__file__).parent / "data" / "gold" / "grounding_gold.json"

_ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
# numbers NOT part of identifier-like tokens (doc:sent:tok line ids, sha hex)
_NUM_RE = re.compile(r"(?<![\w:.:-])-?\d+(?:\.\d+)?%?")
_ABSENCE_RE = re.compile(
    r"\b(no|none|not found|no results|no hits|zero|does not (?:occur|appear|exist)|"
    r"not (?:listed|present|among)|isn't (?:listed|present)|0\b|"
    r"لا يوجد|لا توجد|أي نتائج|صفر|ليس (?:موجود|بين|ضمن)|لم يظهر)\b",
    re.IGNORECASE,
)
_ERROR_RE = re.compile(
    r"\b(error|invalid|failed|fails|syntax|cannot parse|could not (?:parse|run)|"
    r"not a valid|malformed|خطأ|فشل|غير صالح)\b",
    re.IGNORECASE,
)
_NO_TOOL_RE = re.compile(
    r"\b(no tool|not available|cannot be grounded|cannot ground|no such (?:tool|measure)|"
    r"not (?:exposed|supported|computed)|unable to|do not have|doesn't (?:expose|provide)|"
    r"لا أستطيع|غير متاح|لا يوجد (?:قبل|مقياس)|لا يمكن)\b",
    re.IGNORECASE,
)


def normalize_text(text: str) -> str:
    """Arabic-Indic digits -> ASCII; unify whitespace."""
    return re.sub(r"\s+", " ", text.translate(_ARABIC_INDIC)).strip()


def extract_numbers(text: str) -> list[float]:
    """Extract statistic candidates: numbers not embedded in id-like tokens."""
    cleaned = normalize_text(text)
    # drop identifier-like tokens (line ids 'doc:1:2', hex ids, versions like v2.0.0)
    cleaned = re.sub(r"\b\w+:\d+:\d+\b", " ", cleaned)
    cleaned = re.sub(r"\b[0-9a-f]{8,}\b", " ", cleaned)
    cleaned = re.sub(r"\bv?\d+\.\d+\.\d+\b", " ", cleaned)  # version strings
    out: list[float] = []
    for m in _NUM_RE.finditer(cleaned):
        tok = m.group(0)
        val = float(tok.rstrip("%"))
        out.append(val)
    return out


def _numbers_in(obj: Any) -> list[float]:
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_numbers_in(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_numbers_in(v))
    return out


def _matches(quoted: float, gold: float, tol: float) -> bool:
    if quoted == gold:
        return True
    if tol == 0:
        # integer counts match exactly; bounded fractions accept percent forms
        if 0.0 < gold <= 1.0:
            return quoted <= 100.0 and abs(quoted / 100.0 - gold) <= 0.005
        return False
    if abs(quoted - gold) <= max(tol, abs(gold) * 0.005, 0.005):
        return True
    return 0.0 < quoted <= 100.0 and abs(quoted / 100.0 - gold) <= max(tol, abs(gold) * 0.005)


def _contains(haystack: str, needle: str, language: str) -> bool:
    h = normalize_text(haystack)
    n = normalize_text(needle)
    if language == "en":
        h, n = h.lower(), n.lower()
    return n in h


def score_question(q: dict[str, Any], run_entry: dict[str, Any] | None) -> dict[str, Any]:
    gold = q["gold"]
    allowed: set[float] = set()
    for t in q["tools"]:
        if t.get("ok"):
            allowed.update(round(v, 9) for v in _numbers_in(t.get("result")))
    verdict = "PASS"
    detail: dict[str, Any] = {
        "missing": [], "hallucinated": [], "matched": [], "notes": [],
    }
    if run_entry is None:
        return {"id": q["id"], "verdict": "NO_ANSWER", "detail": detail}
    answer = normalize_text(str(run_entry.get("answer", "")))
    tool_errors = [t for t in q["tools"] if not t.get("ok", True)]
    quoted = [v for v in extract_numbers(answer)]
    traps = gold.get("traps", {})

    def fail(kind: str, note: str) -> None:
        nonlocal verdict
        if verdict == "PASS":
            verdict = kind
        detail["notes"].append(note)

    # --- trap contract first: it is the question's primary requirement ---
    if not answer:
        fail("NO_ANSWER", "empty answer")
    if traps.get("no_tool"):
        if not _NO_TOOL_RE.search(answer):
            fail("TRAP_FAILURE", "no-tool trap: answer does not state unavailability")
        if quoted:
            fail("TRAP_FAILURE", f"no-tool trap: answer quotes numbers {quoted}")
    elif traps.get("error"):
        if not _ERROR_RE.search(answer):
            fail("TRAP_FAILURE", "error trap: answer does not acknowledge the failure")
    elif q.get("trap"):
        if not _ABSENCE_RE.search(answer):
            fail("TRAP_FAILURE", "zero-match trap: answer lacks an explicit zero/absence marker")
    else:
        if traps.get("absent") and not _ABSENCE_RE.search(answer):
            fail("TRAP_FAILURE", f"expected-absent ({traps['absent']}): answer lacks an absence marker")
        for t in tool_errors:
            if not _ERROR_RE.search(answer):
                fail("TRAP_FAILURE", f"tool failed ({t.get('error', '')[:60]!r}) but answer ignores it")

    for num in quoted:
        if not any(_matches(num, a, 1e-9) for a in allowed):
            detail["hallucinated"].append(num)
    if detail["hallucinated"]:
        fail("HALLUCINATED", f"numbers not in any tool output: {detail['hallucinated']}")

    for gnum in gold["numbers"]:
        value = gnum["value"]
        if isinstance(value, list):  # list_each: every value must appear
            for v in value:
                if any(_matches(x, v, gnum["tol"]) for x in quoted):
                    detail["matched"].append({gnum["label"]: v})
                else:
                    detail["missing"].append({gnum["label"]: v})
            continue
        hit = next((x for x in quoted if _matches(x, value, gnum.get("tol", 1e-6))), None)
        if hit is None:
            detail["missing"].append({gnum["label"]: value})
        else:
            detail["matched"].append({gnum["label"]: value})
    if detail["missing"]:
        fail("MISSING_NUMBER", f"gold numbers not quoted: {detail['missing']}")

    for gstr in gold["strings"]:
        if not _contains(answer, gstr["value"], q["language"]):
            fail("MISSING_NUMBER", f"gold string not quoted: {gstr['label']}={gstr['value']!r}")
        else:
            detail["matched"].append({gstr["label"]: gstr["value"]})
    return {"id": q["id"], "verdict": verdict, "detail": detail}


def bootstrap_ci(values: list[int], n_boot: int = 2000, seed: int = 42) -> tuple[float, float]:
    """95% CI for a proportion via bootstrap over question-level 0/1 values."""
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means = []
    n = len(values)
    for _ in range(n_boot):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return (means[int(0.025 * n_boot)], means[int(0.975 * n_boot) - 1])


def score_run(gold_doc: dict[str, Any], run_doc: dict[str, Any]) -> dict[str, Any]:
    gold_by_id = {q["id"]: q for q in gold_doc["questions"]}
    run_by_id = {e["id"]: e for e in run_doc.get("results", [])}
    verdicts: list[dict[str, Any]] = []
    for qid, q in gold_by_id.items():
        verdicts.append(score_question(q, run_by_id.get(qid)))

    categories: dict[str, dict[str, int]] = {}
    for v in verdicts:
        cat = gold_by_id[v["id"]]["category"]
        slot = categories.setdefault(cat, {"n": 0, "pass": 0})
        slot["n"] += 1
        if v["verdict"] == "PASS":
            slot["pass"] += 1
    passes = [1 if v["verdict"] == "PASS" else 0 for v in verdicts]
    halluc = [
        1 if v["verdict"] == "HALLUCINATED" or v["detail"]["hallucinated"] else 0
        for v in verdicts
    ]
    lo_p, hi_p = bootstrap_ci(passes)
    lo_h, hi_h = bootstrap_ci(halluc)
    n = len(verdicts)
    summary = {
        "questions": n,
        "pass_rate": sum(passes) / n if n else 0.0,
        "pass_rate_ci95": [lo_p, hi_p],
        "hallucination_rate": sum(halluc) / n if n else 0.0,
        "hallucination_rate_ci95": [lo_h, hi_h],
        "verdict_counts": {},
        "per_category": {
            k: {"n": s["n"], "pass_rate": s["pass"] / s["n"] if s["n"] else 0.0}
            for k, s in sorted(categories.items())
        },
    }
    verdict_counts: dict[str, int] = {}
    for v in verdicts:
        verdict_counts[v["verdict"]] = verdict_counts.get(v["verdict"], 0) + 1
    summary["verdict_counts"] = verdict_counts
    return {
        "summary": summary,
        "verdicts": verdicts,
        "meta": {
            "gold_meta": gold_doc["_meta"],
            "run_meta": run_doc.get("meta", {}),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Score a grounding run against frozen gold")
    ap.add_argument("run", help="run JSON produced by eval.run_grounding")
    ap.add_argument("--gold", default=str(_DEFAULT_GOLD))
    ap.add_argument("--out", default=None, help="write full report JSON here")
    ap.add_argument("--verbose", action="store_true", help="print per-question verdicts")
    args = ap.parse_args()
    gold_doc = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    run_doc = json.loads(Path(args.run).read_text(encoding="utf-8"))
    report = score_run(gold_doc, run_doc)
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    s = report["summary"]
    print(
        f"pass {s['pass_rate']:.1%} (CI95 {s['pass_rate_ci95'][0]:.1%}-{s['pass_rate_ci95'][1]:.1%}) | "
        f"hallucination {s['hallucination_rate']:.1%} | verdicts {s['verdict_counts']}"
    )
    for cat, st in s["per_category"].items():
        print(f"  {cat:14s} {st['pass_rate']:6.1%}  (n={st['n']})")
    if args.verbose:
        for v in report["verdicts"]:
            if v["verdict"] != "PASS":
                print(f"  {v['id']}: {v['verdict']} — {v['detail']['notes']}")
    if not s["questions"]:
        print("WARNING: run file contained no matching results", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
