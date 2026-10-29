"""Benchmark: Arabic Tools analysis at corpus scale (100K / 500K / 1M tokens).

Measures the REAL production path - nlp.arabic.pipeline.analyze_arabic
(CAMeL calima-msa-r13 morphology) and identify_arabic_dialect (DIDModel6) -
on synthetic Arabic corpora of 100K, 500K and 1M tokens, so the default
CORPUSMIND_ARABIC_TIMEOUT_S can be judged against evidence instead of hope.

v2.0.0 manuscript additions (additive; defaults preserve the original
single-repetition behaviour):
  - --reps N: repeated timed runs per size (gc.collect() between reps),
    reporting median / min / max / CV% alongside every raw repetition.
  - --sizes / --reps / --out / --label CLI (the CORPUSMIND_ARABIC_BENCH_SIZES
    env var still works as the --sizes fallback).
  - a "_meta" provenance block (UTC timestamp, commit SHA, runner info,
    Python/CAMeL versions, exact command, corpus construction) so results are
    reviewer-verifiable per common academic practice.

Run:  python scripts/benchmark_arabic_corpus.py [--sizes 20000,100000] [--reps 3]
Env:  CORPUSMIND_ARABIC_BENCH_SIZES=100000,500000,1000000  (token counts)

Corpus-construction caveat (documented, by design): the corpus repeats the 8
SENTENCES below, so after the 2k-token warmup the morphology cache is warm and
tok/s reflects steady-state production-path throughput on repetitive text,
not cold-cache cost. `_meta.unique_input_tokens` records the vocabulary size
of every measured input so readers can judge this.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

# The engine reads the data dir at import; make sure the resolver finds the
# provisioned pack on this machine before anything imports camel_tools.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

# Sentence pool: real MSA with regular morphology, plus Gulf/Egy/Lev samples
# for the dialect path. Repeated with light variation to build N tokens.
SENTENCES = [
    "الطلاب يدرسون في المكتبة الكبيرة ويقرأون الكتب المفيدة كل صباح.",
    "يكتب الكاتب في المكتبة كتابا مفيدا للطلاب في الجامعة.",
    "قال المعلم للطلاب إن الاجتهاد طريق النجاح في الحياة.",
    "شلون الحال اليوم وين رايح بعد الدرس يا صديقي.",
    "عايز أروح البيت دلوقتي لأن عندي شغل كتير بإذن الله.",
    "شو رأيك بالخبر اللي وصلنا هلق من البيروت اليوم.",
    "اللغة العربية من أغنى لغات العالم في المفردات والجذور.",
    "ذهب المسافر إلى المطار مبكرا لأن الطائرة أقلعت في الصباح.",
]


def build_corpus(n_tokens: int) -> str:
    base = " ".join(SENTENCES)
    per_rep = len(base.split())
    reps = max(1, n_tokens // per_rep)
    return " ".join([base] * reps)


def _summary(rows: list[dict]) -> dict:
    """median/min/max/CV% summary over per-rep rows."""
    speeds = [r["tokens_per_s"] for r in rows if r.get("tokens_per_s")]
    if not speeds:
        return {}
    med = statistics.median(speeds)
    return {
        "median_tokens_per_s": round(med, 1),
        "min_tokens_per_s": round(min(speeds), 1),
        "max_tokens_per_s": round(max(speeds), 1),
        "cv_pct": round(100 * statistics.pstdev(speeds) / statistics.mean(speeds), 2)
        if len(speeds) > 1 and statistics.mean(speeds) > 0 else 0.0,
    }


def bench_analyze(tokens: int, reps: int) -> dict:
    from nlp.arabic.pipeline import analyze_arabic

    text = build_corpus(tokens)
    actual_tokens = len(text.split())
    runs: list[dict] = []
    analysis = None
    for i in range(reps):
        gc.collect()
        t0 = time.perf_counter()
        analysis = analyze_arabic(text, dialect="msa")
        elapsed = time.perf_counter() - t0
        runs.append({
            "rep": i + 1,
            "elapsed_s": round(elapsed, 2),
            "tokens_per_s": round(actual_tokens / elapsed, 1) if elapsed > 0 else None,
            "est_500k_s": round(500000 / (actual_tokens / elapsed), 1) if elapsed > 0 else None,
            "est_1m_s": round(1000000 / (actual_tokens / elapsed), 1) if elapsed > 0 else None,
        })
    out = {
        "path": "analyze_arabic (calima-msa-r13)",
        "input_tokens": actual_tokens,
        "output_tokens": len(analysis.tokens),
        "reps": runs,
        **_summary(runs),
    }
    # legacy single-run fields, now defined as the MEDIAN repetition
    med = sorted(runs, key=lambda r: r["tokens_per_s"] or 0)[len(runs) // 2]
    out["elapsed_s"] = med["elapsed_s"]
    out["tokens_per_s"] = med["tokens_per_s"]
    out["est_500k_s"] = med["est_500k_s"]
    out["est_1m_s"] = med["est_1m_s"]
    return out


def bench_dialect(tokens: int, reps: int) -> dict:
    from nlp.arabic.pipeline import identify_arabic_dialect

    text = build_corpus(tokens)
    actual_tokens = len(text.split())
    runs: list[dict] = []
    result: dict = {"dialect_distribution": {}}
    for i in range(reps):
        gc.collect()
        t0 = time.perf_counter()
        result = identify_arabic_dialect(text, include_cities=False)
        elapsed = time.perf_counter() - t0
        runs.append({
            "rep": i + 1,
            "elapsed_s": round(elapsed, 2),
            "tokens_per_s": round(actual_tokens / elapsed, 1) if elapsed > 0 else None,
        })
    out = {
        "path": "identify_arabic_dialect (DIDModel6)",
        "input_tokens": actual_tokens,
        "reps": runs,
        **_summary(runs),
    }
    med = sorted(runs, key=lambda r: r["tokens_per_s"] or 0)[len(runs) // 2]
    out["elapsed_s"] = med["elapsed_s"]
    out["tokens_per_s"] = med["tokens_per_s"]
    out["top_bucket"] = max(result["dialect_distribution"], key=result["dialect_distribution"].get)
    return out


def _git_commit() -> str | None:
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5,
            cwd=Path(__file__).resolve().parent.parent,
        ).stdout.strip() or None
    except Exception:
        return None


def _meta(label: str, sizes: list[int], reps: int) -> dict:
    meta: dict = {
        "utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "label": label,
        "command": " ".join([sys.executable.split("/")[-1]] + sys.argv[1:]),
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "commit": _git_commit(),
        "github": {
            k: os.environ[k] for k in (
                "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_NUMBER",
                "GITHUB_RUN_ATTEMPT", "RUNNER_NAME", "RUNNER_OS", "RUNNER_ARCH",
            ) if k in os.environ
        },
        "sizes": sizes,
        "reps": reps,
        "corpus_construction": (
            "the 8 SENTENCES repeated to the target token count; after the 2k warmup "
            "the morphology cache is warm, so tok/s measures steady-state "
            "production-path throughput on repetitive text"
        ),
    }
    try:
        import importlib.metadata as md

        meta["camel_tools"] = md.version("camel-tools")
    except Exception:
        meta["camel_tools"] = "not importable"
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description="Arabic pipeline corpus-scale benchmark")
    ap.add_argument("--sizes", default=os.environ.get("CORPUSMIND_ARABIC_BENCH_SIZES",
                                                      "100000,500000,1000000"),
                    help="comma-separated token counts")
    ap.add_argument("--reps", type=int, default=1, help="timed repetitions per size")
    ap.add_argument("--out", default=None,
                    help="output JSON path (default download/arabic_corpus_benchmark.json)")
    ap.add_argument("--label", default="local", help="run label recorded in _meta")
    args = ap.parse_args()

    sizes = [int(s) for s in str(args.sizes).split(",") if s.strip()]
    reps = max(1, args.reps)
    results: dict = {
        "_meta": _meta(args.label, sizes, reps),
        "sizes": sizes,
        "analyze": [],
        "dialect": [],
    }

    # Warm load first (DB load time is reported separately, not in tok/s).
    t0 = time.perf_counter()
    bench_analyze(2000, 1)
    load_and_2k = time.perf_counter() - t0
    results["cold_load_and_2k_s"] = round(load_and_2k, 2)
    print(f"[bench] cold load + 2k tokens: {load_and_2k:.2f}s")

    for size in sizes:
        r = bench_analyze(size, reps)
        results["analyze"].append(r)
        print(f"[bench] analyze  {size:>8} tokens x{reps}: median "
              f"{r['median_tokens_per_s']} tok/s (min {r['min_tokens_per_s']}, "
              f"max {r['max_tokens_per_s']}, cv {r['cv_pct']}%) "
              f"-> est 500k={r['est_500k_s']}s, 1m={r['est_1m_s']}s")

    # Warm the dialect-ID model outside the timed reps (rep 1 would otherwise
    # include the one-time model load; that load time is reported separately).
    t0 = time.perf_counter()
    from nlp.arabic.pipeline import identify_arabic_dialect as _dialect_warm

    _dialect_warm(build_corpus(2000), include_cities=False)
    results["dialect_model_load_and_2k_s"] = round(time.perf_counter() - t0, 2)
    print(f"[bench] dialect model load + 2k tokens: {results['dialect_model_load_and_2k_s']}s")

    for size in sizes:
        r = bench_dialect(size, reps)
        results["dialect"].append(r)
        print(f"[bench] dialect  {size:>8} tokens x{reps}: median "
              f"{r['median_tokens_per_s']} tok/s (min {r['min_tokens_per_s']}, "
              f"max {r['max_tokens_per_s']}, cv {r['cv_pct']}%) (top={r['top_bucket']})")

    # vocabulary-size validity signal for the repetitive-corpus caveat
    probe = build_corpus(sizes[0]) if sizes else build_corpus(2000)
    results["_meta"]["unique_input_tokens"] = len(set(probe.split()))

    dest = Path(args.out) if args.out else (
        Path(__file__).resolve().parent.parent / "download" / "arabic_corpus_benchmark.json"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[bench] wrote {dest}")


if __name__ == "__main__":
    main()
