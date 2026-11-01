"""A6/F3 stats parity: CorpusMind vs scipy / statsmodels / lexicalrichness.

Compares the engine's measures against reference implementations on TWO
corpus sets and ONE contingency-table battery:

1. Hash-frozen snapshot texts in engine/eval/data/snapshot (8 corpora) plus
   "en_all" (concatenation of the four en_* texts) — 29..369 tokens each.
2. F3 synthetic long texts (10k / 50k / 100k tokens, deterministic seeded
   Zipf-like sampling, numpy PCG64 seed 20261031) — these make window/segment
   measures (MATTR(50), STTR(1000)) genuinely comparable, which the short
   snapshot texts cannot: LR RAISES on inputs shorter than its window, so on
   the snapshot set those measures have n_comparable=0.

Both sides always receive the SAME token list (shared regex tokenizer ``\\w+``
over the snapshot texts; the synthetic texts are generated as token lists
directly), so every deviation is a real implementation/convention difference.

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

F3 2x2 battery (>= 300 tables, including small and zero counts):
  - every (a,b,c,d) in {0,1,2,3,5}^4 — 625 tables, zero cells in every position
  - the deterministic corpus-derived table ("the" in the two largest en corpora)
  - 150 seeded random tables with cells in [0,200] and 100 in [0,5000]
  - degenerate tables (all-zero, zero row, zero column) fall out of the grid
  Tables where EITHER side returns a non-finite value (scipy raises or returns
  nan/inf on zero margins; the engine returns inf for undefined odds ratios)
  are EXCLUDED and counted, never folded into a deviation statistic — an
  empty comparison is reported as NOT_TESTED, never as zero deviation.

compare() semantics (F3 fix): if a measure has NO comparable rows, its report
carries status "NOT_TESTED" with max_abs_dev = max_rel_dev = null. Deviation
maxima are computed over comparable rows only.

Usage (from engine/):
    python -m eval.parity_stats [--snapshot-dir data/snapshot]
        [--out parity.json] [--skip-battery] [--skip-synthetic]
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from collections.abc import Callable
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
    from stats.measures import guiraud
except ImportError:  # pragma: no cover - older layout
    guiraud = None  # type: ignore[assignment]

TOKEN_RE = re.compile(r"\w+", re.UNICODE)

SYNTH_SEED = 20261031
SYNTH_SIZES = (10_000, 50_000, 100_000)
SYNTH_VOCAB = 200_000
SYNTH_A = 1.25  # Zipf shape


def load_corpora(snapshot_dir: Path) -> dict[str, list[str]]:
    texts: dict[str, str] = {}
    for p in sorted(snapshot_dir.glob("*.txt")):
        texts[p.stem] = p.read_text(encoding="utf-8")
    en_keys = sorted(k for k in texts if k.startswith("en_"))
    if len(en_keys) >= 2:
        texts["en_all"] = "\n".join(texts[k] for k in en_keys)
    return {k: TOKEN_RE.findall(v) for k, v in texts.items()}


def synthetic_corpora() -> dict[str, list[str]]:
    """F3: deterministic long texts so window measures become comparable.

    Tokens are drawn from a Zipf-like distribution (numpy zipf(a=1.25) mapped
    modulo the vocabulary) with a fixed PCG64 seed — no text files, no
    tokenizer: the exact same token list goes to both sides.
    """
    import numpy as np

    rng = np.random.Generator(np.random.PCG64(SYNTH_SEED))
    out: dict[str, list[str]] = {}
    for size in SYNTH_SIZES:
        draws = rng.zipf(SYNTH_A, size=size)
        out[f"synth_{size//1000}k"] = [f"w{int(d) % SYNTH_VOCAB}" for d in draws]
    return out


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
    """F3 fix: an empty/uncomparable comparison is NOT_TESTED, never 0/0."""
    rows: list[dict[str, Any]] = []
    for k in sorted(engine_vals):
        e, r = engine_vals[k], ref_vals.get(k)
        if r is None:
            continue
        comparable = math.isfinite(e) and math.isfinite(r)
        abs_dev = abs(e - r) if comparable else math.nan
        rel_dev = (abs_dev / abs(r)
                   if comparable and r else (0.0 if comparable and not abs_dev else math.nan))
        rows.append({"corpus": k, "engine": e, "reference": r,
                     "abs_dev": abs_dev, "rel_dev": rel_dev,
                     "comparable": comparable})
    finite = [r for r in rows if math.isfinite(float(r["abs_dev"]))]
    n_excluded = sum(1 for r in rows if not r["comparable"])
    if not finite:
        # NOT_TESTED: no row compares — report nulls, never a zero deviation.
        return {"measure": note.split(" — ")[0], "rows": rows,
                "status": "NOT_TESTED", "max_abs_dev": None, "max_rel_dev": None,
                "note": note, "n_comparable": 0, "n_excluded": n_excluded}
    max_abs = max(float(r["abs_dev"]) for r in finite)
    max_rel = max((float(r["rel_dev"]) for r in finite if math.isfinite(float(r["rel_dev"]))), default=0.0)
    return {"measure": note.split(" — ")[0], "rows": rows,
            "status": "OK", "max_abs_dev": max_abs, "max_rel_dev": max_rel,
            "note": note, "n_comparable": len(finite), "n_excluded": n_excluded}


def battery_tables(corpora: dict[str, list[str]]) -> list[dict[str, Any]]:
    """F3: >= 300 deterministic 2x2 tables, small and zero cells included."""
    tables: list[dict[str, Any]] = []
    # 1. exhaustive small grid {0,1,2,3,5}^4 (625 tables, zeros everywhere)
    for a in (0, 1, 2, 3, 5):
        for b in (0, 1, 2, 3, 5):
            for c in (0, 1, 2, 3, 5):
                for d in (0, 1, 2, 3, 5):
                    tables.append({"cells": (a, b, c, d), "kind": "small_grid"})
    # 2. the deterministic corpus-derived table
    _cks, (a, b, c, d) = corpus_2x2(corpora)
    tables.append({"cells": (a, b, c, d), "kind": "corpus"})
    # 3. seeded random tables at two magnitude scales
    import random

    rng = random.Random(SYNTH_SEED)
    for _ in range(150):
        tables.append({"cells": tuple(rng.randint(0, 200) for _ in range(4)),
                       "kind": "random_small"})
    for _ in range(100):
        tables.append({"cells": tuple(rng.randint(0, 5000) for _ in range(4)),
                       "kind": "random_large"})
    return tables


def run_battery(corpora: dict[str, list[str]]) -> list[dict[str, Any]]:
    """Compare chi-square / G^2 / odds-ratio over the whole battery."""
    import numpy as np
    import scipy.stats as st
    from statsmodels.stats.contingency_tables import Table2x2

    tables = battery_tables(corpora)
    out: list[dict[str, Any]] = []
    specs = [
        ("chi_square_2x2", "Pearson chi-square, Yates correction DISABLED on the scipy side "
         "(scipy default is corrected — convention checked, engine is raw); scipy raises "
         "on zero margins — those tables are excluded, not zero-dev"),
        ("log_likelihood_2x2", "Dunning G^2 = 2*sum(O*ln(O/E)) with independence expected "
         "counts; reference scipy.stats.power_divergence(lambda_='log-likelihood') on the "
         "same 2x2 — same convention, no continuity correction"),
        ("odds_ratio", "uncorrected sample odds ratio; reference statsmodels "
         "Table2x2(table, shift_zeros=False).oddsratio — the statsmodels DEFAULT "
         "shift_zeros=True silently applies the Haldane 0.5 correction (convention "
         "trap, verified in source) and would match the engine's separate "
         "odds_ratio_haldane instead; engine maps (f1, f2, N1, N2) = (a, c, a+b, c+d); "
         "tables where the raw OR is UNDEFINED (b == 0 or c == 0) are excluded — the "
         "engine returns 0.0/inf there by convention and statsmodels would divide by zero"),
    ]
    # B023 (ruff 0.17): the dispatch table must not close over loop
    # variables — each lambda takes the four cells explicitly.
    engine_fns: dict[str, Any] = {
        "chi_square_2x2": lambda a, b, c, d: chi_square_2x2(a, b, c, d),
        "log_likelihood_2x2": lambda a, b, c, d: log_likelihood_2x2(a, b, c, d),
        "odds_ratio": lambda a, b, c, d: odds_ratio(a, c, a + b, c + d),
    }
    for name, note in specs:
        rows: list[dict[str, Any]] = []
        for t in tables:
            a, b, c, d = t["cells"]
            try:
                e_val = float(engine_fns[name](a, b, c, d))
            except Exception:
                e_val = math.nan
            try:
                table = np.array([[a, b], [c, d]], dtype=float)
                if name == "chi_square_2x2":
                    r_val = float(st.chi2_contingency(table, correction=False)[0])
                elif name == "log_likelihood_2x2":
                    _chi2, _p, _dof, expected = st.chi2_contingency(table, correction=False)
                    r_val = float(st.power_divergence(table.ravel(), expected.ravel(),
                                                      lambda_="log-likelihood")[0])
                else:
                    # shift_zeros=False: statsmodels' DEFAULT Table2x2 applies the
                    # Haldane 0.5 shift to zero cells (verified: Table2x2 stores
                    # [[0.5,1],[1,2]] for input [[0,1],[1,2]]) — that is the CORRECTED
                    # OR, not the sample OR the engine computes. The default quietly
                    # matches the engine's separate odds_ratio_haldane, not odds_ratio.
                    r_val = float(Table2x2(table, shift_zeros=False).oddsratio)
            except Exception:
                r_val = math.nan
            # F3: the raw sample OR is UNDEFINED when b == 0 or c == 0. There the
            # engine returns 0.0/inf by convention while statsmodels returns
            # placeholder values (observed 1.0, 2.0, ...) — neither is the OR,
            # so such tables are EXCLUDED for the odds-ratio comparison instead
            # of being scored as (meaningless) agreements or deviations.
            defined = (name != "odds_ratio") or (b > 0 and c > 0)
            comparable = (defined and math.isfinite(e_val) and math.isfinite(r_val))
            abs_dev = abs(e_val - r_val) if comparable else math.nan
            rel_dev = (abs_dev / abs(r_val)
                       if comparable and r_val else (0.0 if comparable and not abs_dev else math.nan))
            rows.append({"cells": list(t["cells"]), "kind": t["kind"],
                         "engine": e_val, "reference": r_val,
                         "abs_dev": abs_dev, "rel_dev": rel_dev,
                         "comparable": comparable})
        finite = [r for r in rows if r["comparable"]]
        zero_cell = [r for r in rows if 0 in r["cells"]]
        zero_cell_ok = [r for r in zero_cell if r["comparable"]]
        if not finite:
            out.append({"measure": name, "status": "NOT_TESTED",
                        "n_tables": len(rows), "n_comparable": 0,
                        "n_excluded": len(rows), "max_abs_dev": None,
                        "max_rel_dev": None, "note": note, "rows_example": []})
            continue
        excluded_examples = [
            {"cells": r["cells"], "kind": r["kind"],
             "engine": r["engine"] if math.isfinite(r["engine"]) else str(r["engine"]),
             "reference": r["reference"] if math.isfinite(r["reference"]) else str(r["reference"])}
            for r in rows if not r["comparable"]][:3]
        out.append({
            "measure": name, "status": "OK",
            "n_tables": len(rows), "n_comparable": len(finite),
            "n_excluded": len(rows) - len(finite),
            "max_abs_dev": max(r["abs_dev"] for r in finite),
            "max_rel_dev": max((r["rel_dev"] for r in finite
                                if math.isfinite(r["rel_dev"])), default=0.0),
            "zero_cell_tables": len(zero_cell),
            "zero_cell_comparable": len(zero_cell_ok),
            "zero_cell_max_abs_dev": (max(r["abs_dev"] for r in zero_cell_ok)
                                      if zero_cell_ok else None),
            "excluded_examples": excluded_examples,
            "note": note,
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="A6/F3 stats parity (scipy/statsmodels/lexicalrichness)")
    ap.add_argument("--snapshot-dir", default=str(Path(__file__).parent / "data" / "snapshot"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--skip-battery", action="store_true")
    ap.add_argument("--skip-synthetic", action="store_true")
    args = ap.parse_args()

    from lexicalrichness import LexicalRichness

    corpora = load_corpora(Path(args.snapshot_dir))
    if not corpora:
        raise SystemExit("no snapshot texts found")
    if not args.skip_synthetic:
        synth = synthetic_corpora()
        corpora.update(synth)

    results: list[dict[str, Any]] = []

    # ---- lexicalrichness family (same token list on both sides) ----
    # LR 0.5.x preprocesses (lowercase, strip punctuation/digits) and re-tokenizes
    # by default. To keep the SHARED-TOKENIZER premise, LR is constructed with an
    # identity preprocessor and a tokenizer that returns the exact shared token
    # list. LR's default-preprocessing token counts are still recorded as drift
    # disclosure (they explain any naive-LR numbers a reader may reproduce).
    lr_objs = {k: LexicalRichness(" ".join(t), preprocessor=lambda x: x,
                                 tokenizer=lambda _s, toks=t: toks)
               for k, t in corpora.items()}
    lr_default = {k: LexicalRichness(" ".join(t)) for k, t in corpora.items()}
    tok_note = ("shared regex tokenizer \\w+; LR pinned to the same list via "
                "preprocessor=identity + tokenizer=closure; LR default "
                "preprocessing drift recorded per corpus; synth_* are F3 "
                "deterministic Zipf-like texts (seed 20261031)")
    tok_match = {k: lr.words == len(corpora[k]) for k, lr in lr_objs.items()}
    tok_drift_default = {k: {"shared": len(corpora[k]), "lr_default": lr.words}
                         for k, lr in lr_default.items()}

    def _ev(fn: Callable[[list[str]], float]) -> dict[str, float]:
        return {k: fn(t) for k, t in corpora.items()}

    def _rv(attr: str, **kw: Any) -> dict[str, float]:
        out = {}
        for k, lr in lr_objs.items():
            try:
                out[k] = float(getattr(lr, attr)(**kw)) if kw else float(getattr(lr, attr))
            except Exception:
                out[k] = math.nan
        return out

    def _skip_none(vals: dict[str, float], min_len: int) -> dict[str, float]:
        # LR raises on inputs shorter than its window; drop those corpora so the
        # comparison only covers rows where BOTH tools define the measure.
        return {k: v for k, v in vals.items()
                if len(corpora[k]) >= min_len and math.isfinite(v)}

    results.append(compare(_ev(type_token_ratio),
                           _skip_none(_rv("ttr"), 0),
        "TTR — identical definition (types/tokens) on the shared token list"))
    results.append(compare(_ev(lambda t: mattr(t, window=50)),
                           _skip_none(_rv("mattr", window_size=50), 50),
        "MATTR window=50 — both average TTR over every full window, stride 1; "
        "corpora shorter than the window are EXCLUDED on the LR side (LR raises) "
        "while the engine falls back to raw TTR — convention difference, disclosed, "
        "not scored; F3 synth texts make the comparison real"))
    results.append(compare(_ev(lambda t: sttr(t, chunk_size=1000)),
                           _skip_none(_rv("msttr", segment_window=1000), 1000),
        "STTR chunk=1000 — both split into NON-overlapping 1000-token segments and "
        "average per-segment TTR; trailing handling DIFFERS (checked, disclosed): the "
        "engine drops only a trailing PARTIAL chunk (documented standard practice) "
        "while LR msttr(discard=True) deletes the LAST segment unconditionally — when "
        "n is an exact multiple of the window that discards one full segment "
        "(LR source: segment_generator yields all segments, then `del scores[-1]`). "
        "Residual relative deviation <= ~1/segment_count (observed 2.6e-3 on the F3 "
        "synth texts); convention difference, not an engine bug. Corpora shorter "
        "than the chunk are EXCLUDED (LR raises, engine falls back to raw TTR); on "
        "the snapshot set alone this measure is NOT_TESTED (F3: n_comparable=0 is "
        "NOT TESTED, never 0/0) — the synth 10k/50k/100k texts provide comparables"))
    results.append(compare(_ev(lambda t: mtld(t, threshold=0.72)), _rv("mtld", threshold=0.72),
        "MTLD threshold=0.72 — AGGREGATION CONVENTION DIFFERS (checked, disclosed): "
        "engine = len(tokens)/mean(forward_factors, backward_factors); LR = mean of the "
        "two directional MTLD scores (len/factors each) — the McCarthy & Jarvis 2010 "
        "published form. Equal iff forward==backward factor counts; residual gap is "
        "this convention, not a bug. Per-corpus rows show where the passes diverge"))
    results.append(compare(_ev(lambda t: hd_d(t, sample_size=42)), _rv("hdd", draws=42),
        "HD-D sample=42 — McCarthy & Jarvis hypergeometric sampling; LR 0.5.x names "
        "the parameter 'draws' (same quantity), engine names it 'sample_size'"))
    if guiraud is not None:
        results.append(compare(_ev(guiraud), _rv("rttr"),
            "Guiraud RTTR — types/sqrt(tokens); identical definition"))

    # ---- F3 battery: >=300 2x2 tables incl small and zero counts ----
    battery = [] if args.skip_battery else run_battery(corpora)
    results.extend(battery)

    report = {
        "shared_corpus": sorted(corpora.keys()),
        "corpus_tokens": {k: len(t) for k, t in corpora.items()},
        "tokenizer": tok_note,
        "lr_token_count_matches": tok_match,
        "lr_default_preproc_drift": tok_drift_default,
        "battery": {"n_tables": sum(m.get("n_tables", 0) for m in battery),
                    "measures": [m["measure"] for m in battery]},
        "sign_convention": "deviation = |engine - reference|; rel_dev = abs_dev/|reference|",
        "measures": results,
    }
    print(json.dumps({k: v for k, v in report.items() if k != "measures"},
                     ensure_ascii=False, indent=1))
    for m in results:
        status = m.get("status", "OK")
        ma = m.get("max_abs_dev")
        mr = m.get("max_rel_dev")
        ma_s = "n/a" if ma is None else f"{ma:.6g}"
        mr_s = "n/a" if mr is None else f"{mr:.6g}"
        extra = (f" n_tables={m['n_tables']} excl={m['n_excluded']}"
                 if "n_tables" in m else f" n_excl={m.get('n_excluded', 0)}")
        print(f"{m['measure']:18} [{status}] max_abs_dev={ma_s} "
              f"max_rel_dev={mr_s}{extra}")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"report written: {args.out}")


if __name__ == "__main__":
    main()
