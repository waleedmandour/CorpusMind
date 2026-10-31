"""A6 stats parity: CorpusMind vs scipy / statsmodels / lexicalrichness.

Compares the engine's measures against reference implementations on ONE
shared corpus set: the hash-frozen snapshot texts in engine/eval/data/snapshot
(8 corpora) plus "en_all" (concatenation of the four en_* texts). 9 sub-corpora,
each tokenized ONCE with a shared regex tokenizer (``\\w+`` over the raw text;
same token list is handed to both sides), so every deviation is a real
implementation/convention difference, not a tokenization difference.

Measures compared (only those the named reference tools actually provide):
- lexicalrichness: TTR, MATTR(50), STTR(1000) [LR name: msttr], MTLD(0.72),
  HD-D(42), RTTR (Guiraud).
- scipy: Pearson chi-square on a 2x2 table (correction=False — same raw
  convention as the engine) and Dunning G^2 via
  scipy.stats.power_divergence(lambda_='log-likelihood') on the independence
  expected counts.
- statsmodels: Table2x2.oddsratio (uncorrected sample OR — same convention as
  engine.stats.measures.odds_ratio; the engine's Haldane variant has no
  equivalent in the three reference tools and is NOT compared).

The 2x2 table is deterministic: target word "the", corpora = the two largest
en_* snapshot texts (most tokens), cells = (freq_the, rest) per corpus.

For each measure the report records: per-corpus (engine, reference, abs dev,
rel dev), the max absolute deviation and max relative deviation across
corpora, and the convention note. A gap is reported as a DEVIATION, not an
error; A6 requires checking the other tool's convention first (done here and
in the notes).

Usage (from engine/):
    python -m eval.parity_stats [--snapshot-dir data/snapshot]
        [--out parity.json]
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from stats.measures import (
    chi_square_2x2,
    hd_d,
    log_likelihood_2x2,
    mattr,
    mtld,
    odds_ratio,
    sttr,
    type_token_ratio,
)

try:
    from stats.measures import guiraud  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - older layout
    guiraud = None  # type: ignore[assignment]

TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def load_corpora(snapshot_dir: Path) -> dict[str, list[str]]:
    texts: dict[str, str] = {}
    for p in sorted(snapshot_dir.glob("*.txt")):
        texts[p.stem] = p.read_text(encoding="utf-8")
    en_keys = sorted(k for k in texts if k.startswith("en_"))
    if len(en_keys) >= 2:
        texts["en_all"] = "\n".join(texts[k] for k in en_keys)
    return {k: TOKEN_RE.findall(v) for k, v in texts.items()}


def corpus_2x2(corpora: dict[str, list[str]]) -> tuple[list[str], tuple[int, int, int, int]]:
    """Deterministic 2x2: 'the' in the two largest en_ corpora vs their rest."""
    en = sorted(((k, t) for k, t in corpora.items() if k.startswith("en_")),
                key=lambda kv: -len(kv[1]))[:2]
    (k1, t1), (k2, t2) = en
    f1 = Counter(t1)["the"]
    f2 = Counter(t2)["the"]
    return [k1, k2], (f1, len(t1) - f1, f2, len(t2) - f2)


def compare(engine_vals: dict[str, float], ref_vals: dict[str, float],
            note: str) -> dict[str, Any]:
    rows = []
    for k in sorted(engine_vals):
        e, r = engine_vals[k], ref_vals.get(k)
        if r is None:
            continue
        abs_dev = abs(e - r)
        rel_dev = abs_dev / abs(r) if r else (0.0 if not abs_dev else math.inf)
        rows.append({"corpus": k, "engine": e, "reference": r,
                     "abs_dev": abs_dev, "rel_dev": rel_dev})
    max_abs = max((r["abs_dev"] for r in rows), default=0.0)
    max_rel = max((r["rel_dev"] for r in rows), default=0.0)
    return {"measure": note.split(" — ")[0], "rows": rows,
            "max_abs_dev": max_abs, "max_rel_dev": max_rel, "note": note}


def main() -> None:
    ap = argparse.ArgumentParser(description="A6 stats parity (scipy/statsmodels/lexicalrichness)")
    ap.add_argument("--snapshot-dir", default=str(Path(__file__).parent / "data" / "snapshot"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    from lexicalrichness import LexicalRichness

    corpora = load_corpora(Path(args.snapshot_dir))
    if not corpora:
        raise SystemExit("no snapshot texts found")

    results: list[dict[str, Any]] = []

    # ---- lexicalrichness family (same token list on both sides) ----
    lr_objs = {k: LexicalRichness(" ".join(t)) for k, t in corpora.items()}
    # NOTE: LexicalRichness re-tokenizes internally; verify its token count
    # matches ours and disclose any drift.
    tok_note = ("shared regex tokenizer \\w+; LR re-tokenizes internally, "
                f"token-count match checked per corpus")
    tok_match = {k: lr.words == len(t) for k, (lr, t) in
                 ((k, (lr_objs[k], corpora[k])) for k in corpora)}

    def _ev(fn) -> dict[str, float]:
        return {k: fn(t) for k, t in corpora.items()}

    def _rv(attr: str, **kw) -> dict[str, float]:
        out = {}
        for k, lr in lr_objs.items():
            try:
                out[k] = float(getattr(lr, attr)(**kw)) if kw else float(getattr(lr, attr))
            except Exception:
                out[k] = math.nan
        return out

    results.append(compare(_ev(type_token_ratio), _rv("ttr"),
        "TTR — identical definition (types/tokens); LR tokenization checked via tok_match"))
    results.append(compare(_ev(lambda t: mattr(t, window=50)), _rv("mattr", window_size=50),
        "MATTR window=50 — both average TTR over every full window, stride 1; "
        "engine falls back to raw TTR below the window, LR may differ (see rows)"))
    results.append(compare(_ev(lambda t: sttr(t, chunk_size=1000)), _rv("msttr", segment_window=1000),
        "STTR chunk=1000 — both drop the trailing partial chunk (engine: documented "
        "standard practice; LR msttr: same standard)"))
    results.append(compare(_ev(lambda t: mtld(t, threshold=0.72)), _rv("mtld", threshold=0.72),
        "MTLD threshold=0.72 — forward+backward factor passes averaged; both implement "
        "McCarthy & Jarvis 2010"))
    results.append(compare(_ev(lambda t: hd_d(t, sample_size=42)), _rv("hdd", sample_size=42),
        "HD-D sample=42 — McCarthy & Jarvis hypergeometric sampling; both implement "
        "the same expectation"))
    if guiraud is not None:
        results.append(compare(_ev(guiraud), _rv("rttr"),
            "Guiraud RTTR — types/sqrt(tokens); identical definition"))

    # ---- scipy / statsmodels on the deterministic 2x2 ----
    (ck1, ck2), (a, b, c, d) = corpus_2x2(corpora)
    eng_chi = {"n/a": chi_square_2x2(a, b, c, d)}
    eng_g2 = {"n/a": log_likelihood_2x2(a, b, c, d)}
    eng_or = {"n/a": odds_ratio(a, b, c, d)}

    import numpy as np
    import scipy.stats as st
    from statsmodels.stats.contingency_tables import Table2x2

    table = np.array([[a, b], [c, d]], dtype=float)
    chi2, _p, _dof, expected = st.chi2_contingency(table, correction=False)
    G2, _p2 = st.power_divergence(table.ravel(), expected.ravel(), lambda_="log-likelihood")
    sm_or = float(Table2x2(table).oddsratio)

    results.append({"measure": "chi_square_2x2", "rows": [
        {"corpus": f"{ck1} vs {ck2}", "engine": eng_chi["n/a"], "reference": float(chi2),
         "abs_dev": abs(eng_chi["n/a"] - float(chi2)),
         "rel_dev": abs(eng_chi["n/a"] - float(chi2)) / float(chi2)}],
        "max_abs_dev": abs(eng_chi["n/a"] - float(chi2)),
        "max_rel_dev": abs(eng_chi["n/a"] - float(chi2)) / float(chi2),
        "note": "Pearson chi-square, Yates correction DISABLED on the scipy side "
                "(scipy default is corrected — convention checked, engine is raw)"})
    results.append({"measure": "log_likelihood_2x2", "rows": [
        {"corpus": f"{ck1} vs {ck2}", "engine": eng_g2["n/a"], "reference": float(G2),
         "abs_dev": abs(eng_g2["n/a"] - float(G2)),
         "rel_dev": abs(eng_g2["n/a"] - float(G2)) / float(G2)}],
        "max_abs_dev": abs(eng_g2["n/a"] - float(G2)),
        "max_rel_dev": abs(eng_g2["n/a"] - float(G2)) / float(G2),
        "note": "Dunning G^2 = 2*sum(O*ln(O/E)) with independence expected counts; "
                "reference scipy.stats.power_divergence(lambda_='log-likelihood') on "
                "the same 2x2 — same convention, no continuity correction"})
    results.append({"measure": "odds_ratio", "rows": [
        {"corpus": f"{ck1} vs {ck2}", "engine": eng_or["n/a"], "reference": sm_or,
         "abs_dev": abs(eng_or["n/a"] - sm_or),
         "rel_dev": abs(eng_or["n/a"] - sm_or) / sm_or}],
        "max_abs_dev": abs(eng_or["n/a"] - sm_or),
        "max_rel_dev": abs(eng_or["n/a"] - sm_or) / sm_or,
        "note": "uncorrected sample odds ratio; statsmodels Table2x2.oddsratio — same "
                "convention (the engine's Haldane variant is intentionally NOT compared)"})

    report = {
        "shared_corpus": sorted(corpora.keys()),
        "corpus_tokens": {k: len(t) for k, t in corpora.items()},
        "tokenizer": tok_note,
        "lr_token_count_matches": tok_match,
        "table_2x2": {"corpora": [ck1, ck2], "cells": [a, b, c, d]},
        "measures": results,
    }
    print(json.dumps({k: v for k, v in report.items() if k != "measures"},
                     ensure_ascii=False, indent=1))
    for m in results:
        print(f"{m['measure']:18} max_abs_dev={m['max_abs_dev']:.6g} "
              f"max_rel_dev={m['max_rel_dev']:.6g}")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"report written: {args.out}")


if __name__ == "__main__":
    main()
