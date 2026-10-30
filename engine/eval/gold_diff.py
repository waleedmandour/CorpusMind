"""Full gold diff: rebuild ALL question golds and diff against the frozen file.

Why (review finding, 2026-10-30): "frozen gold unaffected" was never actually
established. The only live check (``tests/test_eval_grounding.py::
test_gold_rebuild_subset_matches_frozen``) rebuilds TWO questions (G-001,
G-003) — both English, neither sentence-scoped. The Arabic sentence-scoped
questions (G-044, G-056, G-074, possibly G-002) recompute sentence counts,
so ANY splitter change (v2.0.1's terminal-run collapse / semicolon demotion /
quote-parity guard, #39's same-line closer) can shift their frozen values
silently. This script rebuilds the whole bank and diffs, per question:

- ``gold``  — the frozen answer values (numbers/strings/traps);
- ``tools`` — the frozen raw tool outputs (upstream drift provenance).

Exit 1 on ANY difference (or a question missing from the rebuild), with a
human-readable table and a machine-readable JSON report. A clean run is the
gate the grounding re-runs were missing; per the harness discipline, any
non-empty diff is a REVIEWED event: either the engine changed (re-freeze the
gold in a PR, with the diff attached) or the rebuild drifted (fix the
rebuild, never the gold).

Usage (from engine/):
    python -m eval.gold_diff                # report + exit code
    python -m eval.gold_diff --out /tmp/gold_diff.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval.build_gold import build

_GOLD_PATH = Path(__file__).parent / "data" / "gold" / "grounding_gold.json"


def _brief(value: Any, limit: int = 120) -> str:
    s = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return s if len(s) <= limit else s[: limit - 3] + "..."


async def diff(out: Path | None) -> int:
    if not _GOLD_PATH.exists():
        print(f"frozen gold not present: {_GOLD_PATH}", file=sys.stderr)
        return 2
    frozen = json.loads(_GOLD_PATH.read_text(encoding="utf-8"))
    frozen_by_id = {q["id"]: q for q in frozen["questions"]}

    # build(None) raises SystemExit(1) itself if the rebuild fails.
    doc = await build(None)
    rebuilt = {q["id"]: q for q in doc["questions"]}

    diffs: list[dict[str, str]] = []
    for qid in sorted(set(frozen_by_id) | set(rebuilt)):
        f, r = frozen_by_id.get(qid), rebuilt.get(qid)
        if f is None:
            diffs.append({"id": qid, "kind": "not_in_frozen",
                          "field": "-", "frozen": "-", "rebuilt": _brief(r["gold"])})
            continue
        if r is None:
            diffs.append({"id": qid, "kind": "rebuild_failed",
                          "field": "-", "frozen": _brief(f["gold"]), "rebuilt": "-"})
            continue
        if r["gold"] != f["gold"]:
            diffs.append({"id": qid, "kind": "gold_diff", "field": "gold",
                          "frozen": _brief(f["gold"]), "rebuilt": _brief(r["gold"])})
        if r["tools"] != f["tools"]:
            diffs.append({"id": qid, "kind": "tool_result_diff", "field": "tools",
                          "frozen": f"{len(f['tools'])} tool result(s)",
                          "rebuilt": f"{len(r['tools'])} tool result(s)"})

    report = {
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "frozen_meta": frozen.get("_meta", {}),
        "rebuilt_meta": doc.get("_meta", {}),
        "frozen_count": len(frozen_by_id),
        "rebuilt_count": len(rebuilt),
        "clean": not diffs,
        "diffs": diffs,
    }
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"report written: {out}")

    if diffs:
        print(f"\nGOLD DIFF: {len(diffs)} difference(s) between the rebuilt bank "
              f"({len(rebuilt)} questions) and the frozen gold "
              f"({len(frozen_by_id)} questions):\n")
        for d in diffs:
            print(f"  [{d['kind']}] {d['id']}")
            print(f"    frozen : {d['frozen']}")
            print(f"    rebuilt: {d['rebuilt']}")
        print("\nA non-empty gold diff is a REVIEWED event: either the engine's "
              "outputs changed (re-freeze the gold in a reviewed PR, with this "
              "report attached) or the rebuild drifted (fix the rebuild, never "
              "the gold). Do NOT re-run grounding against a stale gold.")
        return 1
    print(f"gold diff clean: all {len(rebuilt)} rebuilt golds and tool results "
          f"match the frozen file ({len(frozen_by_id)} questions).")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Rebuild all gold questions and diff vs the frozen gold")
    ap.add_argument("--out", default=None,
                    help="JSON report path (default eval/runs/gold_diff.json)")
    args = ap.parse_args()
    out = Path(args.out) if args.out else Path(__file__).parent / "runs" / "gold_diff.json"
    raise SystemExit(asyncio.run(diff(out)))


if __name__ == "__main__":
    main()
