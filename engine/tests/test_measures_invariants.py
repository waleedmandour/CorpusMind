"""F6 — statistical invariant & golden guard suite (the v2.0.0 golden battery).

The regression net that would have caught the four statistical bugs fixed
in F1–F4 (HD-D scale, DP-norm bound, Log Ratio/%DIFF ±inf, BH q-values).
Three independent layers:

1. Bounds properties — seeded random inputs (~300 cases) asserting every
   measure stays inside its mathematically guaranteed range for ANY valid
   input, and that the keyness battery is always finite/JSON-safe.
2. Golden fixtures — ``tests/data/goldens/measures_v2.json`` holds a fixed
   battery of 37 inputs (distinct/Zipf/sparse texts, equal/unequal parts,
   zero-cell keyness tables) with expected outputs generated ONCE from the
   fixed code and cross-checked at generation time against independent
   references (exact ``math.comb`` hypergeometrics for HD-D, ``Fraction``
   rational arithmetic for DP-norm/Juilland, algebraically split log paths
   for the keyness battery, the literal nested-min BH definition,
   brute-force per-window slicing for MATTR). Three of those references are
   re-derived live inside this file so the fixture and the engine must ALSO
   agree with first principles, not merely with themselves.
3. Optional cross-implementation check — if the published
   ``lexical-diversity`` package happens to be installed, HD-D must agree
   with its ``hdd()`` on the golden texts. Skipped otherwise (it is NOT a
   project dependency; CI installs none of it).

Any future accidental change to a formula fails this suite loudly.
"""
from __future__ import annotations

import json
import math
import random
from collections import Counter
from fractions import Fraction
from math import comb
from pathlib import Path
from typing import Any

import pytest

from stats.measures import (
    benjamini_hochberg,
    compute_keyness_row,
    gries_dp_norm,
    hd_d,
    juillands_d,
    keyness_ll,
    log_dice,
    log_ratio,
    mattr,
    p_value_ll,
    pct_diff,
    sttr,
    type_token_ratio,
)

_GOLDENS_PATH = Path(__file__).parent / "data" / "goldens" / "measures_v2.json"


def _load_goldens() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(_GOLDENS_PATH.read_text(encoding="utf-8"))
    return raw


def _assert_golden(got: float, expected: float | str, label: str) -> None:
    """Compare a recomputed value against its golden (JSON carries '-inf' as a string)."""
    exp = float(expected)
    if math.isinf(exp):
        assert got == exp, label
    else:
        assert got == pytest.approx(exp, rel=1e-9, abs=1e-12), label


# --------------------------------------------------------------------------- #
# Independent references, re-derived live (mirrors the generator's checks)
# --------------------------------------------------------------------------- #


def _hdd_exact(tokens: list[str], sample_size: int) -> float:
    """Exact hypergeometric HD-D: Σ_types (1 − C(N−f, b)/C(N, b)) / b."""
    n = len(tokens)
    b = min(sample_size, n)
    if n <= sample_size:
        return len(set(tokens)) / n
    return sum(1 - comb(n - f, b) / comb(n, b) for f in Counter(tokens).values()) / b


def _dp_norm_exact(observed: list[int], sizes: list[int] | None) -> float:
    """Exact-rational DP-norm via fractions.Fraction (no float intermediate)."""
    n = len(observed)
    total = sum(observed)
    if n == 0 or total == 0:
        return 0.0
    if sizes is not None and sum(sizes) > 0 and len(sizes) == n:
        size_total = sum(sizes)
        expected = [Fraction(s, size_total) for s in sizes]
    else:
        expected = [Fraction(1, n)] * n
    dp = Fraction(1, 2) * sum(
        abs(Fraction(f, total) - e) for f, e in zip(observed, expected, strict=True)
    )
    if n < 2:
        return float(dp)
    return float(dp / (1 - min(expected)))


def _bh_literal(p_values: list[float]) -> list[float]:
    """Literal BH definition: q_i = min over ranks j ≥ rank_i of (n/j)·p_(j)."""
    n = len(p_values)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: p_values[i])
    q = [1.0] * n
    for rank, idx in enumerate(order, start=1):
        candidates = [p_values[order[pos]] * n / (pos + 1) for pos in range(rank - 1, n)]
        q[idx] = min(1.0, min(candidates))
    return q


# --------------------------------------------------------------------------- #
# 1. Bounds properties (seeded, ~300 cases)
# --------------------------------------------------------------------------- #


def test_bounds_hd_d_seeded() -> None:
    rng = random.Random(606)
    for _ in range(40):
        n_types = rng.randrange(1, 120)
        n_tokens = rng.randrange(n_types, 900)
        toks = [f"w{rng.randrange(n_types)}" for _ in range(n_tokens)]
        v = hd_d(toks)
        assert 0.0 < v <= 1.0  # never zero for a non-empty text, never above 1
        s = rng.randrange(2, 80)
        assert 0.0 < hd_d(toks, sample_size=s) <= 1.0


def test_bounds_gries_dp_norm_seeded() -> None:
    rng = random.Random(607)
    for _ in range(40):
        n = rng.randrange(2, 9)
        obs = [rng.randrange(0, 50) for _ in range(n)]
        if sum(obs) == 0:
            obs[rng.randrange(n)] = 1
        assert 0.0 <= gries_dp_norm(obs) <= 1.0  # uniform expected proportions
        sizes = [rng.randrange(1, 200) for _ in range(n)]
        v = gries_dp_norm(obs, sizes=sizes)  # any part sizes
        assert 0.0 <= v <= 1.0


def test_bounds_log_dice_seeded() -> None:
    rng = random.Random(608)
    for _ in range(30):
        fx = rng.randrange(1, 500)
        fy = rng.randrange(1, 500)
        joint = rng.randrange(0, min(fx, fy) + 1)
        v = log_dice(joint, fx, fy)
        assert v <= 14.0  # Dice ∈ (0, 1] ⇒ LogDice ≤ 14
        if joint > 0:
            assert math.isfinite(v) and v > float("-inf")


def test_keyness_effect_sizes_finite_for_any_nonnegative_ints_seeded() -> None:
    """The JSON-safety invariant: Log Ratio and %DIFF are finite for ANY
    non-negative ints (frequencies deliberately allowed to exceed corpus
    sizes) — ±inf broke JSON.parse clients before F4."""
    rng = random.Random(609)
    for _ in range(40):
        n1 = rng.randrange(1, 5000)
        n2 = rng.randrange(1, 5000)
        f1 = rng.randrange(0, 2 * n1 + 1)
        f2 = rng.randrange(0, 2 * n2 + 1)
        assert math.isfinite(log_ratio(f1, f2, n1, n2))
        assert math.isfinite(pct_diff(f1, f2, n1, n2))


def test_bounds_keyness_ll_and_p_value_seeded() -> None:
    rng = random.Random(610)
    for _ in range(30):
        n1 = rng.randrange(1, 3000)
        n2 = rng.randrange(1, 3000)
        f1 = rng.randrange(0, n1 + 1)
        f2 = rng.randrange(0, n2 + 1)
        ll = keyness_ll(f1, f2, n1, n2)
        assert math.isfinite(ll)
        assert ll >= -1e-9  # G² ≥ 0 mathematically; −1e-9 absorbs float noise
        p = p_value_ll(ll)
        # χ²(1) survival function. May legitimately underflow to 0.0 for
        # astronomically large LL (erfc(x) < 1e-308 for x > ~27) — the bound
        # is therefore inclusive at both ends.
        assert 0.0 <= p <= 1.0


def test_bounds_juillands_d_seeded() -> None:
    rng = random.Random(611)
    for _ in range(30):
        n = rng.randrange(2, 9)
        freqs = [rng.randrange(0, 100) for _ in range(n)]
        if sum(freqs) == 0:
            freqs[rng.randrange(n)] = 1
        assert 0.0 <= juillands_d(freqs) <= 1.0


def test_bounds_lexical_diversity_seeded() -> None:
    rng = random.Random(612)
    vocab = [f"w{i}" for i in range(300)]
    for _ in range(30):
        toks = [rng.choice(vocab) for _ in range(rng.randrange(1, 800))]
        for v in (
            type_token_ratio(toks),
            mattr(toks, window=rng.randrange(5, 60)),
            sttr(toks, chunk_size=rng.randrange(10, 200)),
        ):
            assert 0.0 < v <= 1.0  # non-empty text ⇒ strictly positive, ≤ 1


def test_bounds_benjamini_hochberg_seeded() -> None:
    rng = random.Random(613)
    for _ in range(30):
        n = rng.randrange(2, 60)
        ps = [rng.random() for _ in range(n)]
        qs = benjamini_hochberg(ps)
        assert len(qs) == n
        for p, q in zip(ps, qs, strict=True):
            assert q >= p - 1e-12  # q dominates p (step-up property)
            assert 0.0 <= q <= 1.0


def test_keyness_battery_json_safe_seeded() -> None:
    """The whole shipped battery must serialize without ±inf/NaN —
    ``allow_nan=False`` raises on exactly the values that broke exports."""
    rng = random.Random(614)
    for _ in range(20):
        n1, n2 = rng.randrange(1, 2000), rng.randrange(1, 2000)
        row = compute_keyness_row("t", rng.randrange(0, n1 + 1), rng.randrange(0, n2 + 1), n1, n2)
        json.dumps(row.measures, allow_nan=False)  # raises if any measure is inf/NaN


# --------------------------------------------------------------------------- #
# 2. Golden fixtures
# --------------------------------------------------------------------------- #


def test_golden_fixture_shape() -> None:
    """Guard the fixture itself against accidental truncation."""
    data = _load_goldens()
    expected_families = {
        "hd_d",
        "gries_dp_norm",
        "juillands_d",
        "log_dice",
        "keyness_rows",
        "p_value_ll",
        "benjamini_hochberg",
        "mattr",
        "sttr",
        "type_token_ratio",
    }
    assert expected_families <= set(data)
    total = sum(len(v) for k, v in data.items() if not k.startswith("_"))
    assert total >= 30  # the F6 golden battery promises ~30 inputs


def test_golden_hd_d() -> None:
    for case in _load_goldens()["hd_d"]:
        toks: list[str] = case["tokens"].split(" ")
        v = hd_d(toks, sample_size=case.get("sample_size", 42))
        _assert_golden(v, case["expected"], f"hd_d/{case['name']}")


def test_golden_hd_d_cross_checked_against_exact_combinatorics() -> None:
    """Re-derive every golden HD-D case from exact hypergeometric
    combinatorics — a computation path independent of the engine's
    overflow-free product."""
    for case in _load_goldens()["hd_d"]:
        toks: list[str] = case["tokens"].split(" ")
        b: int = case.get("sample_size", 42)
        if len(toks) <= b:
            # short-text fallback: HD-D degenerates to raw TTR
            assert hd_d(toks, sample_size=b) == type_token_ratio(toks)
        else:
            ref = _hdd_exact(toks, b)
            assert hd_d(toks, sample_size=b) == pytest.approx(ref, rel=1e-9), case["name"]


def test_golden_gries_dp_norm() -> None:
    for case in _load_goldens()["gries_dp_norm"]:
        sizes = case["sizes"]  # None for uniform expected proportions
        v = gries_dp_norm(case["observed"], sizes=sizes)
        _assert_golden(v, case["expected"], f"dp/{case['name']}")


def test_golden_gries_dp_norm_cross_checked_against_exact_fractions() -> None:
    for case in _load_goldens()["gries_dp_norm"]:
        ref = _dp_norm_exact(case["observed"], case["sizes"])
        got = gries_dp_norm(case["observed"], sizes=case["sizes"])
        assert got == pytest.approx(ref, rel=1e-9, abs=1e-12), case["name"]


def test_golden_juillands_d() -> None:
    for case in _load_goldens()["juillands_d"]:
        v = juillands_d(case["freqs"])
        _assert_golden(v, case["expected"], f"juilland/{case['name']}")


def test_golden_log_dice() -> None:
    for case in _load_goldens()["log_dice"]:
        v = log_dice(case["joint"], case["fx"], case["fy"])
        _assert_golden(v, case["expected"], f"logdice/{case['name']}")


def test_golden_keyness_rows() -> None:
    """The full §12 battery per table — a change to ANY of the six formulas
    (LL, χ², Log Ratio, %DIFF, Simple Maths, Odds Ratio) fails here."""
    for case in _load_goldens()["keyness_rows"]:
        row = compute_keyness_row(case["term"], case["f1"], case["f2"], case["N1"], case["N2"])
        for key, exp in case["measures"].items():
            _assert_golden(row.measures[key], exp, f"key/{case['name']}/{key}")


def test_golden_p_value_ll() -> None:
    for case in _load_goldens()["p_value_ll"]:
        v = p_value_ll(case["ll"])
        _assert_golden(v, case["expected"], f"pval/ll={case['ll']}")


def test_golden_benjamini_hochberg() -> None:
    for case in _load_goldens()["benjamini_hochberg"]:
        qs = benjamini_hochberg(case["p_values"])
        expected: list[Any] = case["expected"]
        assert len(qs) == len(expected), case["name"]
        for q, exp in zip(qs, expected, strict=True):
            _assert_golden(q, exp, f"bh/{case['name']}")


def test_golden_benjamini_hochberg_cross_checked_against_literal_definition() -> None:
    """The engine's running-minimum must agree with the literal
    min-over-later-ranks definition on every golden vector."""
    for case in _load_goldens()["benjamini_hochberg"]:
        ref = _bh_literal(case["p_values"])
        got = benjamini_hochberg(case["p_values"])
        for g, r in zip(got, ref, strict=True):
            assert g == pytest.approx(r, rel=1e-9, abs=1e-12), case["name"]


def test_golden_mattr() -> None:
    for case in _load_goldens()["mattr"]:
        toks: list[str] = case["tokens"].split(" ")
        v = mattr(toks, window=case["window"])
        _assert_golden(v, case["expected"], f"mattr/{case['name']}")


def test_golden_sttr() -> None:
    for case in _load_goldens()["sttr"]:
        toks: list[str] = case["tokens"].split(" ")
        v = sttr(toks, chunk_size=case["chunk_size"])
        _assert_golden(v, case["expected"], f"sttr/{case['name']}")


def test_golden_type_token_ratio() -> None:
    for case in _load_goldens()["type_token_ratio"]:
        toks: list[str] = case["tokens"].split(" ")
        v = type_token_ratio(toks)
        _assert_golden(v, case["expected"], f"ttr/{case['name']}")


# --------------------------------------------------------------------------- #
# 3. Optional cross-implementation check (skipped by default)
# --------------------------------------------------------------------------- #


def test_hd_d_agrees_with_published_lexical_diversity_package() -> None:
    """F6.3 — cross-implementation check against the published
    ``lexical-diversity`` package. Skipped unless it happens to be installed
    (it is NOT a project dependency; CI and dev environments run without it,
    so this adds no dependency and never blocks)."""
    ld = pytest.importorskip("lexical_diversity")
    hdd = getattr(ld, "hdd", None)
    if hdd is None:
        pytest.skip("installed lexical_diversity exposes no top-level hdd()")
    for case in _load_goldens()["hd_d"]:
        toks: list[str] = case["tokens"].split(" ")
        b: int = case.get("sample_size", 42)
        assert hdd(toks) == pytest.approx(hd_d(toks, sample_size=b), rel=1e-9), case["name"]
