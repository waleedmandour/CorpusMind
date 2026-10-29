"""Render benchmark result JSONs as a GitHub-flavored markdown summary.

Reads a directory containing the battery's outputs and appends markdown tables
to $GITHUB_STEP_SUMMARY (or stdout when --stdout). Missing files are skipped
so partial runs still summarize.

Usage:
    python benchmarks/scripts/summary_md.py benchmarks/out
    python benchmarks/scripts/summary_md.py benchmarks/out --stdout
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def _load(d: Path, name: str) -> dict[str, Any] | None:
    p = d / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _perf_section(out: list[str], data: dict[str, Any]) -> None:
    meta = data.get("_meta", {})
    out.append("## Arabic pipeline throughput (production path)\n")
    out.append(
        f"Runner: `{meta.get('platform', '?')}` · {meta.get('cpu_count', '?')} cores · "
        f"Python {meta.get('python', '?')} · camel-tools {meta.get('camel_tools', '?')} · "
        f"commit `{str(meta.get('commit'))[:12]}` · {meta.get('utc', '')}\n")
    out.append(
        "*Corpus construction:* the 8 fixed benchmark sentences repeated to size "
        f"(unique tokens: {meta.get('unique_input_tokens', '?')}); tok/s is steady-state "
        "throughput with a warm morphology cache.\n")
    for key, title in (("analyze", "analyze_arabic (calima-msa-r13)"),
                       ("dialect", "identify_arabic_dialect (DIDModel6)")):
        rows = data.get(key) or []
        if not rows:
            continue
        out.append(f"\n### {title}\n")
        out.append("| input tokens | reps | median tok/s | min | max | CV% | est 500k (s) | est 1M (s) |")
        out.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
        for r in rows:
            est500 = r.get("est_500k_s", "—") if key == "analyze" else "—"
            est1m = r.get("est_1m_s", "—") if key == "analyze" else "—"
            out.append(
                f"| {r.get('input_tokens')} | {len(r.get('reps', []))} "
                f"| {r.get('median_tokens_per_s')} | {r.get('min_tokens_per_s')} "
                f"| {r.get('max_tokens_per_s')} | {r.get('cv_pct')} | {est500} | {est1m} |")
    out.append("")


def _intrinsic_section(out: list[str], data: dict[str, Any], name: str) -> None:
    task = data.get("task", name.replace("seg_intrinsic_", "").replace(".json", ""))
    out.append(f"## AraSEG segmentation — intrinsic ({task}, dev split)\n")
    out.append("| metric | value |")
    out.append("|---|---:|")
    out.append(f"| documents | {data.get('documents')} |")
    out.append(f"| macro P / R / F1 | {data.get('macro_P'):.4f} / {data.get('macro_R'):.4f} / **{data.get('macro_F1'):.4f}** |")
    out.append(f"| micro P / R / F1 | {data.get('micro_P'):.4f} / {data.get('micro_R'):.4f} / {data.get('micro_F1'):.4f} |")
    out.append(f"| perfectly segmented documents | {data.get('perfect_documents')} / {data.get('documents')} |")
    out.append(f"| boundary TP / FP / FN (micro) | {data.get('micro_tp')} / {data.get('micro_fp')} / {data.get('micro_fn')} |")
    out.append("")


def _downstream_section(out: list[str], data: dict[str, Any], name: str) -> None:
    task = name.replace("seg_downstream_", "").replace(".json", "")
    pairs = data.get("pairs") or []
    if not pairs:
        return
    n = len(pairs)
    mean = lambda k: sum(float(p.get(k) or 0) for p in pairs) / n  # noqa: E731
    out.append(f"## AraSEG segmentation — extrinsic deltas ({task}, {n} documents)\n")
    out.append("Paired engine-vs-gold ingestion; positive delta = gold segmentation changes the measurement.\n")
    out.append("| consumer | mean delta |")
    out.append("|---|---:|")
    out.append(f"| sentence count | {mean('delta_sentences'):+.2f} |")
    out.append(f"| collocation rows | {mean('collocations_rows_delta'):+.2f} |")
    out.append(f"| collocation ΣO | {mean('collocations_sum_O_delta'):+.2f} |")
    out.append(f"| n-gram Σfreq | {mean('ngrams_sum_freq_delta'):+.2f} |")
    out.append(f"| CQL `within sentence` matches | {mean('cql_within_sentence_delta'):+.2f} |")
    out.append(f"| sentiment Δpositive | {mean('sentiment_delta_positive'):+.2f} |")
    out.append(f"| sentiment Δnegative | {mean('sentiment_delta_negative'):+.2f} |")
    out.append(f"| CAF mean sentence length | {mean('caf_delta_mean_sentence_length'):+.4f} |")
    align = [p for p in pairs if p.get("alignment_pair_count")]
    if align:
        out.append(f"| Gale–Church alignment pairs (docs with EN side) | {len(align)} |")
    out.append("")


def main() -> None:
    ap = argparse.ArgumentParser(description="Benchmark markdown summary")
    ap.add_argument("directory", type=Path)
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()

    out: list[str] = []
    perf = _load(args.directory, "perf_arabic.json")
    if perf:
        _perf_section(out, perf)
    for name in ("seg_intrinsic_PA.json", "seg_intrinsic_NP.json"):
        data = _load(args.directory, name)
        if data:
            _intrinsic_section(out, data, name)
    for name in ("seg_downstream_PA.json", "seg_downstream_NP.json"):
        data = _load(args.directory, name)
        if data:
            _downstream_section(out, data, name)

    text = "\n".join(out)
    if not text:
        text = "_No benchmark result files found._\n"
    if args.stdout or not os.environ.get("GITHUB_STEP_SUMMARY"):
        print(text)
    else:
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(text)


if __name__ == "__main__":
    main()
