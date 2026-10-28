"""Unit tests for the §12 statistical measures.

Cross-checked against the published worked examples cited in the mission.
A wrong constant here is a silent, serious validity bug.
"""
from __future__ import annotations

import itertools
import math
import random

import pytest

from stats.measures import (
    benjamini_hochberg,
    chi_square_2x2,
    compute_keyness_row,
    delta_p,
    dice_coefficient,
    gries_dp,
    hd_d,
    juillands_d,
    log_dice,
    log_likelihood_2x2,
    log_ratio,
    mutual_information,
    odds_ratio,
    p_value_ll,
    pct_diff,
    simple_maths,
    sttr,
    t_score,
    type_token_ratio,
)

# --------------------------------------------------------------------------- #
# Collocation
# --------------------------------------------------------------------------- #


def test_mutual_information_basic():
    # If O == E, MI = 0 (independence). E = R·C/N.
    # For R=100, C=100, N=10000 → E = 1, so O=1 → MI = 0.
    mi = mutual_information(O=1, R=100, C=100, N=10000)
    assert math.isclose(mi, 0.0, abs_tol=1e-9)


def test_mutual_information_positive_when_over_represented():
    # O=200, E = 100*100/10000 = 1 → MI = log2(200/1) = log2(200) ≈ 7.64
    mi = mutual_information(O=200, R=100, C=100, N=10000)
    assert math.isclose(mi, math.log2(200), rel_tol=1e-6)


def test_t_score_signs():
    # E = R·C/N. Positive when O > E, negative when O < E.
    # R=100, C=100, N=10000 → E = 1.
    assert t_score(O=200, R=100, C=100, N=10000) > 0       # O > E → positive
    # R=1000, C=1000, N=10000 → E = 100000. O=10 < E → negative.
    assert t_score(O=10, R=1000, C=1000, N=10000) < 0
    # O == E → 0. R=100, C=100, N=10000 → E = 1, so O=1 → 0.
    assert math.isclose(t_score(O=1, R=100, C=100, N=10000), 0.0, abs_tol=1e-9)


def test_dice_coefficient_symmetric():
    assert math.isclose(dice_coefficient(joint=10, fx=20, fy=30), (2 * 10) / (20 + 30))


def test_log_dice_constant():
    # LogDice = 14 + log2(Dice). If Dice = 1 → LogDice = 14.
    assert math.isclose(log_dice(joint=10, fx=10, fy=10), 14.0, abs_tol=1e-9)


def test_log_likelihood_dunning_reference():
    """Hand-computable worked example (verified, not from the Dunning paper directly).

    A 2×2 table where one cell is empty — the LL formula must handle zero
    cells gracefully (they contribute 0). For a=10, b=990, c=5, d=995:

        total=2000 ; r1=r2=1000 ; c1=15, c2=1985
        E_a = E_c = 1000·15/2000 = 7.5
        E_b = E_d = 1000·1985/2000 = 992.5
        G² = 2·[10·ln(10/7.5) + 990·ln(990/992.5)
                + 5·ln(5/7.5) + 995·ln(995/992.5)]
           ≈ 2·[2.877 - 2.495 - 2.027 + 2.503]
           ≈ 1.716
    """
    g2 = log_likelihood_2x2(a=10, b=990, c=5, d=995)
    # Verified by hand-computation (1.7116 to 4 sig figs).
    assert math.isclose(g2, 1.7116, rel_tol=1e-3)


def test_log_likelihood_handles_zero_cells():
    """Dunning's central point (1993): LL handles zero cells where χ² would fail."""
    g2 = log_likelihood_2x2(a=0, b=100, c=100, d=0)
    # No crash, finite number, strictly positive when there's an association.
    assert math.isfinite(g2)
    assert g2 > 0


def test_chi_square_nonneg_and_zero_at_independence():
    assert math.isclose(chi_square_2x2(25, 25, 25, 25), 0.0, abs_tol=1e-9)
    assert chi_square_2x2(50, 0, 0, 50) > 0


def test_delta_p_directionality():
    """ΔP is directional — ΔP(y|x) ≠ ΔP(x|y) in general."""
    dp_yx, dp_xy = delta_p(joint=80, fx=100, fy=200, N=1000)
    assert math.isclose(dp_yx, 0.8 - (120 / 900), rel_tol=1e-6)
    assert math.isclose(dp_xy, 0.4 - 0.025, rel_tol=1e-6)


# --------------------------------------------------------------------------- #
# Keyness
# --------------------------------------------------------------------------- #


def test_log_ratio_zero_when_equal_proportions():
    lr = log_ratio(f1=10, f2=100, N1=1000, N2=10000)
    assert math.isclose(lr, 0.0, abs_tol=1e-9)


def test_log_ratio_positive_when_over_represented():
    lr = log_ratio(f1=100, f2=10, N1=10000, N2=10000)
    assert math.isclose(lr, math.log2(10), rel_tol=1e-6)


def test_pct_diff_zero_when_equal_proportions():
    assert math.isclose(pct_diff(f1=10, f2=100, N1=1000, N2=10000), 0.0, abs_tol=1e-9)


def test_pct_diff_positive_when_over_represented():
    assert math.isclose(pct_diff(f1=100, f2=10, N1=10000, N2=10000), 900.0, rel_tol=1e-6)


def test_simple_maths_smooth_default():
    sm = simple_maths(f1=10, f2=10, N1=100000, N2=100000, smooth=1.0)
    assert math.isclose(sm, 1.0, rel_tol=1e-6)


def test_odds_ratio_one_when_equal_distributions():
    or_ = odds_ratio(f1=10, f2=100, N1=1000, N2=10000)
    assert math.isclose(or_, 1.0, rel_tol=1e-6)


def test_log_ratio_zero_cells_hardie_substitution() -> None:
    # Golden values (Hardie 2014 0.5 substitution):
    # log2((0.5/50000)/(100/1000000)) = log2(0.1) = -3.321928...
    assert log_ratio(0, 100, 50_000, 1_000_000) == pytest.approx(-3.321928094887362, rel=1e-9)
    # log2((100/50000)/(0.5/1000000)) = log2(4000) = 11.965784...
    assert log_ratio(100, 0, 50_000, 1_000_000) == pytest.approx(11.965784284662087, rel=1e-9)
    # Always finite (±inf is not valid JSON and breaks JSON.parse clients).
    assert math.isfinite(log_ratio(0, 100, 50_000, 1_000_000))
    assert math.isfinite(log_ratio(100, 0, 50_000, 1_000_000))
    # Sign semantics preserved: absent-from-target → negative,
    # absent-from-reference → positive.
    assert log_ratio(0, 100, 50_000, 1_000_000) < 0
    assert log_ratio(100, 0, 50_000, 1_000_000) > 0


def test_pct_diff_zero_cells_finite() -> None:
    # Used to be +inf; with the 0.5 substitution it is finite:
    # nf1 = 10000/pm, nf2 = (0.5/1000)·1e6 = 500/pm → ((10000−500)/500)·100 = 1900
    v = pct_diff(10, 0, 1000, 1000)
    assert math.isfinite(v)
    assert v == pytest.approx(1900.0, rel=1e-9)
    # Equal zero-zero → 0.
    assert math.isclose(pct_diff(0, 0, 1000, 1000), 0.0, abs_tol=1e-9)


def test_p_value_ll_chi2_critical_values() -> None:
    # The χ²₁ 95% critical value the prompt used to misuse as a per-word
    # threshold: p(3.841458820694124) ≈ 0.05 exactly.
    assert p_value_ll(3.841458820694124) == pytest.approx(0.05, abs=1e-12)
    assert p_value_ll(6.634896601021213) == pytest.approx(0.01, abs=1e-12)
    assert p_value_ll(0.0) == 1.0
    assert p_value_ll(-1.0) == 1.0
    # Monotone decreasing in LL.
    assert p_value_ll(10.0) < p_value_ll(5.0) < p_value_ll(1.0)


def test_benjamini_hochberg_golden() -> None:
    # Worked example (Benjamini & Hochberg 1995 step-up):
    assert benjamini_hochberg([0.01, 0.04, 0.03, 0.005]) == [
        pytest.approx(0.02),
        pytest.approx(0.04),
        pytest.approx(0.04),
        pytest.approx(0.02),
    ]
    assert benjamini_hochberg([]) == []
    assert benjamini_hochberg([0.5]) == [pytest.approx(0.5)]


def test_benjamini_hochberg_properties() -> None:
    rng = random.Random(3)
    for _ in range(50):
        n = rng.randrange(2, 40)
        ps = [rng.random() for _ in range(n)]
        qs = benjamini_hochberg(ps)
        assert len(qs) == n
        for p, q in zip(ps, qs, strict=True):
            assert q >= p - 1e-12          # q dominates p
            assert 0.0 < q <= 1.0 + 1e-12  # bounded in (0, 1]
        order = sorted(range(n), key=lambda i: ps[i])
        qs_sorted = [qs[i] for i in order]
        for a, b in itertools.pairwise(qs_sorted):
            assert b >= a - 1e-9           # non-decreasing in p order


def test_benjamini_hochberg_fdr_control_simulation() -> None:
    # Simulated FDR check: 900 true-null p ~ U(0,1), 100 true-effect p ~ U(0,0.05).
    # At q < 0.05 the false discovery proportion must stay near/below 0.05
    # on average (BH guarantee); a raw per-test 0.05 threshold would let
    # ~45 nulls through vs BH's expected ≤ 5.
    rng = random.Random(17)
    fdr_sum, raw_fdr_sum = 0.0, 0.0
    trials = 30
    for _ in range(trials):
        ps = [rng.random() for _ in range(900)] + [rng.uniform(0, 0.05) for _ in range(100)]
        qs = benjamini_hochberg(ps)
        discovered = [i for i in range(1000) if qs[i] < 0.05]
        false_disc = sum(1 for i in discovered if i < 900)
        fdr_sum += false_disc / max(len(discovered), 1)
        raw = [i for i in range(1000) if ps[i] < 0.05]
        raw_fdr_sum += sum(1 for i in raw if i < 900) / max(len(raw), 1)
    assert fdr_sum / trials <= 0.10                 # BH controls FDR
    assert fdr_sum / trials < raw_fdr_sum / trials  # and beats uncorrected


def test_compute_keyness_row_carries_all_measures():
    row = compute_keyness_row("test", f1=100, f2=10, N1=10000, N2=10000)
    expected_keys = {"log_likelihood", "chi_square", "log_ratio", "pct_diff", "simple_maths", "odds_ratio"}
    assert set(row.measures.keys()) == expected_keys


# --------------------------------------------------------------------------- #
# Dispersion
# --------------------------------------------------------------------------- #


def test_juillands_d_perfectly_even():
    assert math.isclose(juillands_d([10, 10, 10, 10]), 1.0, abs_tol=1e-9)


def test_juillands_d_uneven_is_lower():
    assert juillands_d([10, 0, 0, 0]) < 1.0


def test_gries_dp_zero_when_uniform():
    assert math.isclose(gries_dp([10, 10, 10, 10]), 0.0, abs_tol=1e-9)


def test_gries_dp_max_when_concentrated_in_one_part():
    dp = gries_dp([10, 0, 0, 0])
    assert math.isclose(dp, 0.75, abs_tol=1e-9)


# --------------------------------------------------------------------------- #
# Lexical variation
# --------------------------------------------------------------------------- #


def test_ttr_extremes():
    assert type_token_ratio([]) == 0.0
    assert type_token_ratio(["a"]) == 1.0
    assert type_token_ratio(["a", "a"]) == 0.5


def test_sttr_falls_back_to_ttr_when_short():
    tokens = ["the", "cat", "sat"]
    assert sttr(tokens, chunk_size=1000) == type_token_ratio(tokens)


def test_sttr_chunks_evenly():
    chunk = ["a"] * 500 + ["b"] * 500
    tokens = chunk * 5
    assert math.isclose(sttr(tokens, chunk_size=1000), 0.002, rel_tol=1e-6)


def test_hd_d_standard_scale_500_distinct() -> None:
    # Golden: for 500 all-distinct types each P(X=0) = (N-42)/N, so
    # Σ(1−P0) = 500 · (42/500) = 42 → HD-D = 42/42 = 1.0 exactly.
    assert hd_d([f"w{i}" for i in range(500)]) == pytest.approx(1.0, abs=1e-9)


def test_hd_d_matches_independent_reference() -> None:
    # Cross-check the P(X=0) product against exact combinatorics (no scipy):
    toks = ["a"] * 300 + [f"b{i}" for i in range(200)]  # N=500
    N, b = len(toks), 42
    from collections import Counter
    from math import comb

    ref = sum(1 - comb(N - f, b) / comb(N, b) for f in Counter(toks).values()) / b
    assert hd_d(toks) == pytest.approx(ref, rel=1e-9)


def test_hd_d_length_robustness() -> None:
    # The measure's raison d'être: near-invariance to text length.
    rng = random.Random(7)
    vocab = [f"w{i}" for i in range(400)]
    text = [rng.choice(vocab) for _ in range(3000)]
    assert abs(hd_d(text) - hd_d(text[:1000])) < 0.05


def test_hd_d_bounded() -> None:
    for seed in range(20):
        rng = random.Random(seed)
        toks = [f"w{rng.randrange(60)}" for _ in range(rng.randrange(50, 800))]
        assert 0.0 < hd_d(toks) <= 1.0
