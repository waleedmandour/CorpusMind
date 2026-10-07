"""Benchmark: Arabic Tools analysis at corpus scale (100K / 500K / 1M tokens).

Measures the REAL production path - nlp.arabic.pipeline.analyze_arabic
(CAMeL calima-msa-r13 morphology) and identify_arabic_dialect (DIDModel6) -
on synthetic Arabic corpora of 100K, 500K and 1M tokens, so the default
CORPUSMIND_ARABIC_TIMEOUT_S can be judged against evidence instead of hope.

Run:  engine/.venv/bin/python scripts/benchmark_arabic_corpus.py
Env:  CORPUSMIND_ARABIC_BENCH_SIZES=100000,500000,1000000  (token counts)
"""

from __future__ import annotations

import json
import os
import sys
import time
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


def bench_analyze(tokens: int) -> dict:
    from nlp.arabic.pipeline import analyze_arabic

    text = build_corpus(tokens)
    actual_tokens = len(text.split())
    t0 = time.perf_counter()
    analysis = analyze_arabic(text, dialect="msa")
    elapsed = time.perf_counter() - t0
    out = {
        "path": "analyze_arabic (calima-msa-r13)",
        "input_tokens": actual_tokens,
        "output_tokens": len(analysis.tokens),
        "elapsed_s": round(elapsed, 2),
        "tokens_per_s": round(actual_tokens / elapsed, 1) if elapsed > 0 else None,
        "est_500k_s": round(500000 / (actual_tokens / elapsed), 1) if elapsed > 0 else None,
        "est_1m_s": round(1000000 / (actual_tokens / elapsed), 1) if elapsed > 0 else None,
    }
    return out


def bench_dialect(tokens: int) -> dict:
    from nlp.arabic.pipeline import identify_arabic_dialect

    text = build_corpus(tokens)
    actual_tokens = len(text.split())
    t0 = time.perf_counter()
    result = identify_arabic_dialect(text, include_cities=False)
    elapsed = time.perf_counter() - t0
    return {
        "path": "identify_arabic_dialect (DIDModel6)",
        "input_tokens": actual_tokens,
        "elapsed_s": round(elapsed, 2),
        "top_bucket": max(result["dialect_distribution"], key=result["dialect_distribution"].get),
    }


def main() -> None:
    sizes_raw = os.environ.get("CORPUSMIND_ARABIC_BENCH_SIZES", "100000,500000,1000000")
    sizes = [int(s) for s in sizes_raw.split(",") if s.strip()]
    results: dict = {"machine_note": sys.platform, "sizes": sizes, "analyze": [], "dialect": []}

    # Warm load first (DB load time is reported separately, not in tok/s).
    t0 = time.perf_counter()
    first = bench_analyze(2000)
    load_and_2k = time.perf_counter() - t0
    results["cold_load_and_2k_s"] = round(load_and_2k, 2)
    print(f"[bench] cold load + 2k tokens: {load_and_2k:.2f}s")

    for size in sizes:
        r = bench_analyze(size)
        results["analyze"].append(r)
        print(f"[bench] analyze  {size:>8} tokens: {r['elapsed_s']:>8}s "
              f"({r['tokens_per_s']} tok/s) -> est 500k={r['est_500k_s']}s, 1m={r['est_1m_s']}s")

    for size in sizes:
        r = bench_dialect(size)
        results["dialect"].append(r)
        print(f"[bench] dialect  {size:>8} tokens: {r['elapsed_s']:>8}s (top={r['top_bucket']})")

    out = Path(__file__).resolve().parent.parent / "download"
    out.mkdir(exist_ok=True)
    dest = out / "arabic_corpus_benchmark.json"
    dest.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"[bench] wrote {dest}")


if __name__ == "__main__":
    main()
