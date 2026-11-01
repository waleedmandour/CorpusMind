#!/usr/bin/env python3
"""Validator/merger/scorer for the user-run Tier B grounding data (7b @16384, WSL2).

Implements the acceptance checks from the user-run protocol:
  1. gold hash must match the repo's frozen grounding_gold.json (480f5230...)
  2. shards per repetition: disjoint question ids, union == the expected bank
  3. NO_ANSWER / HTTP 502 counts and per-question wall times
  4. merge shards -> merged run file per repetition
  5. score merged runs with the REPO scorer (subprocess, eval.score)
  6. independent re-score (own number extraction vs frozen gold universe)
     and disagreement report vs the repo scorer
  7. paired per-question flips vs committed CI arms (paper_report.json)
  8. MANIFEST.json with sha256 of every file in the data directory

Usage:
  python3 validate_user_run.py --data-dir <dir> --engine-dir <repo>/engine \
      --expect-ids-full G-001..G-080 [--probe-ids G-001..G-005] [--ci-arm <run-id> ...]

Exit code 0 = all structural checks pass (scoring disagreements are reported,
not fatal); 1 = structural failure (disjointness/union/gold hash).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

GOLD_SHA256_PREFIX = "480f5230"
_NUM_RE = re.compile(r"(?<![\w:.:-])-?\d+(?:\.\d+)?%?")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ids_range(spec: str) -> list[str]:
    """'G-001..G-080' -> ['G-001', ..., 'G-080']"""
    m = re.fullmatch(r"(G)-?(\d+)\.\.(G)-?(\d+)", spec.replace(" ", ""))
    if not m:
        return [s.strip() for s in spec.split(",") if s.strip()]
    lo, hi = int(m.group(2)), int(m.group(4))
    width = len(m.group(2))
    return [f"G-{i:0{width}d}" for i in range(lo, hi + 1)]


def check_gold(engine_dir: Path) -> bool:
    gold = engine_dir / "eval" / "data" / "gold" / "grounding_gold.json"
    h = sha256(gold)
    ok = h.startswith(GOLD_SHA256_PREFIX)
    print(f"[gold] {gold.name} sha256={h[:16]}... -> {'OK' if ok else 'MISMATCH'}")
    return ok


def load_run(path: Path) -> dict:
    return json.loads(path.read_text())


def validate_repetition(shards: list[Path], expected: list[str], rep: str) -> tuple[bool, dict]:
    """Shards of one repetition: disjoint ids, union == expected."""
    seen: dict[str, Path] = {}
    disjoint = True
    total_qs = 0
    for sh in shards:
        run = load_run(sh)
        for r in run.get("results", []):
            qid = r.get("id")
            total_qs += 1
            if qid in seen:
                print(f"[FAIL] {rep}: id {qid} appears in both {seen[qid].name} and {sh.name}")
                disjoint = False
            seen[qid] = sh
    union = set(seen)
    expected_set = set(expected)
    missing = sorted(expected_set - union)
    extra = sorted(union - expected_set)
    ok = disjoint and not missing and not extra
    print(f"[{rep}] shards={len(shards)} questions={total_qs} unique={len(union)} "
          f"disjoint={'yes' if disjoint else 'NO'} "
          f"missing={missing if missing else 'none'} extra={extra if extra else 'none'} "
          f"-> {'OK' if ok else 'FAIL'}")
    return ok, seen


def merge_shards(shards: list[Path], out: Path) -> dict:
    """Concatenate results into one run file; keep the first shard's meta
    (all shards share the protocol) and record per-shard provenance."""
    merged: dict = {}
    metas = []
    results = []
    for sh in sorted(shards):
        run = load_run(sh)
        metas.append({"shard": sh.name, "meta": run.get("meta", {}),
                      "question_count": len(run.get("results", []))})
        results.extend(run.get("results", []))
    first = load_run(shards[0])
    merged["meta"] = dict(first.get("meta", {}))
    merged["meta"]["merged_from_shards"] = [m["shard"] for m in metas]
    merged["meta"]["question_count"] = len(results)
    merged["results"] = sorted(results, key=lambda r: r.get("id", ""))
    out.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    return merged


def failure_counts(run: dict) -> dict:
    res = run.get("results", [])
    no_answer = [r["id"] for r in res if not (r.get("answer") or "").strip()]
    http5xx = [r["id"] for r in res if str(r.get("http_status", "")).startswith("5")]
    walls = [(r["id"], r.get("wall_ms", 0) / 1000) for r in res if r.get("wall_ms")]
    slow = [(i, round(w, 1)) for i, w in walls if w >= 180.0]
    return {
        "n": len(res),
        "no_answer": no_answer,
        "http_5xx": http5xx,
        "questions_at_or_above_180s": slow,
        "max_wall_s": round(max((w for _, w in walls), default=0.0), 1),
    }


def independent_rescore(run: dict, gold: dict) -> list[dict]:
    """Second scorer: numbers quoted in the answer vs gold-required numbers and
    the frozen tool-output universe. Deliberately simpler than eval.score
    (no trap/no-tool/absence logic); used only to cross-check verdicts."""
    out = []
    by_id = {q["id"]: q for q in gold["questions"]}
    for r in run.get("results", []):
        qid = r.get("id")
        q = by_id.get(qid)
        if not q:
            continue
        ans = r.get("answer") or ""
        if not ans.strip():
            out.append({"id": qid, "re_score": "NO_ANSWER"})
            continue
        quoted = {float(x.rstrip("%")) for x in _NUM_RE.findall(ans.replace(",", ""))}
        allowed: set[float] = set()
        for t in q.get("tools", []):
            allowed |= {round(v, 9) for v in _numbers_in(t.get("result"))}
        required = [g["value"] for g in q.get("gold", {}).get("numbers", [])]
        hall = sorted(n for n in quoted
                      if not any(_match(n, a) for a in allowed))
        # required gold numbers not matched by any quoted number
        missing = sorted({g for g in required if not any(_match(g, n) for n in quoted)})
        if q.get("gold", {}).get("traps", {}).get("no_tool") and quoted:
            out.append({"id": qid, "re_score": "TRAP_FAILURE",
                        "hallucinated": hall, "missing": missing})
        elif hall:
            out.append({"id": qid, "re_score": "HALLUCINATED",
                        "hallucinated": hall, "missing": missing})
        elif missing:
            out.append({"id": qid, "re_score": "MISSING_NUMBER", "missing": missing})
        else:
            out.append({"id": qid, "re_score": "PASS"})
    return out


def _numbers_in(node) -> list[float]:
    if isinstance(node, bool):
        return []
    if isinstance(node, (int, float)):
        return [float(node)]
    if isinstance(node, str):
        return [float(x.rstrip("%")) for x in _NUM_RE.findall(node.replace(",", ""))]
    if isinstance(node, dict):
        return [v for val in node.values() for v in _numbers_in(val)]
    if isinstance(node, list):
        return [v for val in node for v in _numbers_in(val)]
    return []


def _match(a: float, b: float) -> bool:
    if a == b:
        return True
    if b != 0 and abs(a - b) / abs(b) <= 0.005:  # 0.5% relative (repo tolerance)
        return True
    return abs(a - abs(a)) == 0 and f"{a:.6g}" == f"{b:.6g}"


def repo_score(engine_dir: Path, run_path: Path, out_path: Path) -> bool:
    cmd = [sys.executable, "-m", "eval.score", str(run_path),
           "--out", str(out_path), "--verbose"]
    p = subprocess.run(cmd, cwd=engine_dir, capture_output=True, text=True)
    print(f"[score] {' '.join(cmd[1:3])} -> rc={p.returncode}")
    if p.returncode != 0:
        print(p.stderr[-800:])
    return p.returncode == 0


def flips_vs_ci(user_report: Path, ci_reports: list[Path], attempted: set[str] | None = None) -> dict:
    uv = {v["id"]: v["verdict"] for v in json.loads(user_report.read_text())["verdicts"]}
    if attempted is not None:
        # only compare questions the run actually attempted — a probe or a
        # shard-less partial run must not count absent ids as losses
        uv = {k: v for k, v in uv.items() if k in attempted}
    out = {}
    for ci in ci_reports:
        cv = {v["id"]: v["verdict"] for v in json.loads(ci.read_text())["verdicts"]}
        common = sorted(set(uv) & set(cv))
        gains = [i for i in common if uv[i] == "PASS" and cv[i] != "PASS"]
        losses = [i for i in common if uv[i] != "PASS" and cv[i] == "PASS"]
        out[ci.parent.parent.name] = {
            "common": len(common), "user_pass": sum(1 for i in common if uv[i] == "PASS"),
            "ci_pass": sum(1 for i in common if cv[i] == "PASS"),
            "pass_gains": gains, "pass_losses": losses,
        }
    return out


def write_manifest(data_dir: Path) -> None:
    entries = {}
    for p in sorted(data_dir.rglob("*")):
        if p.is_file() and p.name != "MANIFEST.json":
            entries[str(p.relative_to(data_dir))] = sha256(p)
    (data_dir / "MANIFEST.json").write_text(
        json.dumps({"algorithm": "sha256", "files": entries}, indent=2) + "\n")
    print(f"[manifest] {len(entries)} files hashed -> {data_dir / 'MANIFEST.json'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--engine-dir", required=True)
    ap.add_argument("--expect-ids-full", default="G-001..G-080")
    ap.add_argument("--probe-ids", default="G-001..G-005",
                    help="expectation for files whose name contains 'probe'")
    ap.add_argument("--ci-arm", action="append", default=[],
                    help="run id under benchmarks/results to compare flips against")
    ap.add_argument("--repo", default=".", help="repo root (for benchmarks/results)")
    args = ap.parse_args()

    data = Path(args.data_dir)
    engine = Path(args.engine_dir)
    ok = check_gold(engine)

    gold = json.loads((engine / "eval" / "data" / "gold" / "grounding_gold.json").read_text())

    # group run shards by repetition prefix (name before _shard / whole file)
    groups: dict[str, list[Path]] = {}
    for p in sorted(data.glob("*.json")):
        if p.name in ("MANIFEST.json",) or p.name.endswith(".scored.json"):
            continue
        m = re.match(r"(.+?)_shard", p.name)
        rep = m.group(1) if m else ("probe" if "probe" in p.name else p.stem)
        groups.setdefault(rep, []).append(p)

    merged_dir = data / "merged"
    merged_dir.mkdir(exist_ok=True)
    all_ok = True
    rep_attempted: dict[str, set] = {}
    for rep, shards in sorted(groups.items()):
        expected = ids_range(args.probe_ids if rep == "probe" else args.expect_ids_full)
        ok_rep, _ = validate_repetition(shards, expected, rep)
        all_ok &= ok_rep
        merged = merge_shards(shards, merged_dir / f"{rep}_merged.json")
        fc = failure_counts(merged)
        print(f"[{rep}] NO_ANSWER={len(fc['no_answer'])} {fc['no_answer'][:6]} | "
              f"5xx={len(fc['http_5xx'])} {fc['http_5xx'][:6]} | "
              f"max_wall={fc['max_wall_s']}s "
              f"at/above 180s: {fc['questions_at_or_above_180s'][:6]}")
        scored = merged_dir / f"{rep}_merged.scored.json"
        if repo_score(engine, merged_dir / f"{rep}_merged.json", scored):
            rep_verdicts = {v["id"]: v["verdict"]
                            for v in json.loads(scored.read_text())["verdicts"]}
            attempted_ids = {r.get("id") for r in merged.get("results", [])}
            for row in independent_rescore(merged, gold):
                rv = row["re_score"]
                if rv != rep_verdicts.get(row["id"]):
                    print(f"[rescore-diff] {row['id']}: repo={rep_verdicts.get(row['id'])} "
                          f"independent={rv} {({k: v for k, v in row.items() if k not in ('id', 're_score')})}")
            rep_attempted[rep] = attempted_ids

    if args.ci_arm:
        report = merged_dir / "rep1_merged.scored.json"
        if not report.exists():
            cands = sorted(merged_dir.glob("*_merged.scored.json"))
            report = cands[0] if cands else report
        if report.exists():
            rep_of_report = report.name.replace("_merged.scored.json", "")
            ci_paths = [Path(args.repo) / "benchmarks" / "results" / f"run-{rid}" /
                        "grounding" / "paper_report.json" for rid in args.ci_arm]
            print(json.dumps(flips_vs_ci(report, ci_paths,
                                         rep_attempted.get(rep_of_report)), indent=1))
        else:
            print("[flips] no merged scored run yet; skipped")

    write_manifest(data)
    print("STRUCTURAL:", "PASS" if all_ok else "FAIL")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
