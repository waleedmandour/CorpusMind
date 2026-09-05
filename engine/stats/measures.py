"""
Corpus statistics — formulas verbatim from the CorpusMind mission §12.

Each function is pure, typed, and unit-testable against published worked
examples. This is not a place for "creative" deviations: a wrong constant in
a keyness formula is a silent, serious validity bug (§17).

Conventions (matching the mission):
  O = observed joint frequency
  E = expected frequency under independence
  N = corpus size
  R, C = row / column marginal frequencies (R = node freq, C = collocate freq)
  f1, N1 = freq + size of target corpus (keyness)
  f2, N2 = freq + size of reference corpus (keyness)
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Collocation measures
# --------------------------------------------------------------------------- #


def expected_joint(R: int, C: int, N: int) -> float:
    """E = R·C / N  within the chosen span (Church & Hanks 1990)."""
    if N <= 0:
        raise ValueError("N must be positive")
    return (R * C) / N


def mutual_information(O: float, R: int, C: int, N: int) -> float:
    """MI = log2(O / E)  (Church & Hanks 1990)."""
    if O <= 0:
        return float("-inf")
    return math.log2(O / expected_joint(R, C, N))


def t_score(O: float, R: int, C: int, N: int) -> float:
    """T = (O − E) / sqrt(O)."""
    if O <= 0:
        return 0.0
    return (O - expected_joint(R, C, N)) / math.sqrt(O)


def dice_coefficient(joint: int, fx: int, fy: int) -> float:
    """Dice = 2·f(x,y) / (f(x) + f(y))."""
    denom = fx + fy
    if denom <= 0:
        return 0.0
    return (2 * joint) / denom


def log_dice(joint: int, fx: int, fy: int) -> float:
    """LogDice = 14 + log2( 2·f(x,y) / (f(x) + f(y)) )  (Rychlý 2008).

    The +14 constant keeps the score in a friendly range for ranking.
    """
    d = dice_coefficient(joint, fx, fy)
    if d <= 0:
        return float("-inf")
    return 14 + math.log2(d)


def log_likelihood_2x2(a: int, b: int, c: int, d: int) -> float:
    """G² = 2 · Σ Oᵢⱼ · ln(Oᵢⱼ / Eᵢⱼ)  over the 2×2 contingency table (Dunning 1993).

    Cells (a, b, c, d) are the four observed counts:
        a = node-with-collocate        b = node-without-collocate
        c = collocate-without-node     d = neither
    """
    total = a + b + c + d
    if total <= 0:
        return 0.0

    # row / column marginals
    r1, r2 = a + b, c + d
    c1, c2 = a + c, b + d

    def cell(o: int, e: float) -> float:
        return 0.0 if o == 0 else o * math.log(o / e)

    e_a = (r1 * c1) / total
    e_b = (r1 * c2) / total
    e_c = (r2 * c1) / total
    e_d = (r2 * c2) / total

    return 2 * (cell(a, e_a) + cell(b, e_b) + cell(c, e_c) + cell(d, e_d))


def chi_square_2x2(a: int, b: int, c: int, d: int) -> float:
    """Pearson χ² on the 2×2 contingency table."""
    total = a + b + c + d
    if total <= 0:
        return 0.0
    r1, r2 = a + b, c + d
    c1, c2 = a + c, b + d

    def term(o: int, e: float) -> float:
        return 0.0 if e == 0 else ((o - e) ** 2) / e

    return (
        term(a, (r1 * c1) / total)
        + term(b, (r1 * c2) / total)
        + term(c, (r2 * c1) / total)
        + term(d, (r2 * c2) / total)
    )


def delta_p(joint: int, fx: int, fy: int, N: int) -> tuple[float, float]:
    """ΔP = P(y|x) − P(y|¬x), returned in both directions (Gries 2013; Ellis 2007).

    Returns (delta_p_y_given_x, delta_p_x_given_y).
    """
    if fx <= 0 or fy <= 0 or N <= 0:
        return 0.0, 0.0
    # P(y|x) = joint / fx ; P(y|¬x) = (fy - joint) / (N - fx)
    p_y_given_x = joint / fx
    p_y_given_not_x = (fy - joint) / (N - fx) if (N - fx) > 0 else 0.0
    # P(x|y) = joint / fy ; P(x|¬y) = (fx - joint) / (N - fy)
    p_x_given_y = joint / fy
    p_x_given_not_y = (fx - joint) / (N - fy) if (N - fy) > 0 else 0.0
    return p_y_given_x - p_y_given_not_x, p_x_given_y - p_x_given_not_y


# --------------------------------------------------------------------------- #
# Keyness — significance + effect size
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class KeynessRow:
    """One row of a keyness comparison. `measures` carries every computed score
    so the UI can sort/rank by any combination, per §8.7."""
    term: str
    f1: int           # freq in target corpus
    f2: int           # freq in reference corpus
    N1: int           # target corpus size
    N2: int           # reference corpus size
    measures: dict[str, float]


def _norm_freq(f: int, N: int) -> float:
    """Per-million-words normalized frequency."""
    return (f / N) * 1_000_000 if N > 0 else 0.0


def log_ratio(f1: int, f2: int, N1: int, N2: int) -> float:
    """Log Ratio = log2( (f1/N1) / (f2/N2) )  (Hardie 2014) — effect size."""
    if N1 <= 0 or N2 <= 0:
        return 0.0
    if f1 <= 0 and f2 <= 0:
        return 0.0
    if f1 <= 0:
        return float("-inf")  # term absent from target, present in ref
    if f2 <= 0:
        return float("inf")   # term present in target, absent from ref
    return math.log2((f1 / N1) / (f2 / N2))


def pct_diff(f1: int, f2: int, N1: int, N2: int) -> float:
    """%DIFF = ((norm_f1 − norm_f2) / norm_f2) × 100  (Gabrielatos & Marchi 2012)."""
    if N1 <= 0 or N2 <= 0:
        return 0.0
    nf1, nf2 = _norm_freq(f1, N1), _norm_freq(f2, N2)
    if nf2 <= 0:
        return float("inf") if nf1 > 0 else 0.0
    return ((nf1 - nf2) / nf2) * 100


def simple_maths(f1: int, f2: int, N1: int, N2: int, *, smooth: float = 1.0) -> float:
    """Simple Maths = (norm_f1 + SMOOTH) / (norm_f2 + SMOOTH)  (Kilgarriff 2009)."""
    nf1, nf2 = _norm_freq(f1, N1), _norm_freq(f2, N2)
    return (nf1 + smooth) / (nf2 + smooth)


def odds_ratio(f1: int, f2: int, N1: int, N2: int) -> float:
    """Odds Ratio = (f1 · (N2−f2)) / (f2 · (N1−f1))."""
    denom = f2 * (N1 - f1)
    if denom <= 0:
        return float("inf") if f1 > 0 else 0.0
    return (f1 * (N2 - f2)) / denom


def odds_ratio_haldane(f1: int, f2: int, N1: int, N2: int) -> float:
    """Odds Ratio with the Haldane–Anscombe 0.5 continuity correction,
    applied automatically whenever any of the four cells is zero
    (standard practice — the raw OR is undefined/infinite there).
    Identical to :func:`odds_ratio` when no cell is zero."""
    b, d = N1 - f1, N2 - f2
    if f1 > 0 and f2 > 0 and b > 0 and d > 0:
        return odds_ratio(f1, f2, N1, N2)
    return ((f1 + 0.5) * (d + 0.5)) / ((f2 + 0.5) * (b + 0.5))


def fisher_exact_2x2(a: int, b: int, c: int, d: int) -> float:
    """Two-tailed Fisher's exact test on the 2×2 table (hypergeometric).

    Sum of the probabilities of every table (same marginals) whose
    probability is ≤ the observed table's — the standard 'sum of tables not
    more likely' definition. Computed in log-space via lgamma so large
    marginals don't overflow. Sparse-data-safe where χ²/LL are not.
    """
    total = a + b + c + d
    if total <= 0:
        return 0.0
    row1, col1 = a + b, a + c

    def log_hypge(x: int) -> float:
        # log P(x) = log C(row1, x) + log C(total-row1, col1-x) - log C(total, col1)
        def log_choose(n: int, k: int) -> float:
            if k < 0 or k > n:
                return float("-inf")
            return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
        return log_choose(row1, x) + log_choose(total - row1, col1 - x) - log_choose(total, col1)

    a_min = max(0, row1 + col1 - total)
    a_max = min(row1, col1)
    if a_max < a_min:
        return 0.0
    p_obs = log_hypge(a)
    # tables at least as extreme as the observed one (± log tolerance)
    log_sum = float("-inf")
    for x in range(a_min, a_max + 1):
        lp = log_hypge(x)
        if lp <= p_obs + 1e-9:
            # log-space running sum
            if lp == float("-inf"):
                continue
            log_sum = lp if log_sum == float("-inf") else (
                max(log_sum, lp) + math.log1p(math.exp(min(lp, log_sum) - max(lp, log_sum)))
            )
    return min(1.0, math.exp(log_sum)) if log_sum != float("-inf") else 0.0


def chi2_min_expected(a: int, b: int, c: int, d: int) -> float:
    """Smallest expected cell count of the 2×2 table — the Cochran validity
    diagnostic for χ² (all expected cells should be ≥ 5). Callers surface it
    as a warning flag instead of silently trusting χ² on sparse tables."""
    total = a + b + c + d
    if total <= 0:
        return 0.0
    r1, r2 = a + b, c + d
    c1, c2 = a + c, b + d
    return min(r1 * c1, r1 * c2, r2 * c1, r2 * c2) / total


def keyness_ll(f1: int, f2: int, N1: int, N2: int) -> float:
    """Log-likelihood for keyness — 2×2 table where the two corpora are the rows
    and the term-vs-other is the column."""
    return log_likelihood_2x2(a=f1, b=N1 - f1, c=f2, d=N2 - f2)


def keyness_chi2(f1: int, f2: int, N1: int, N2: int) -> float:
    return chi_square_2x2(a=f1, b=N1 - f1, c=f2, d=N2 - f2)


def compute_keyness_row(
    term: str,
    f1: int,
    f2: int,
    N1: int,
    N2: int,
    *,
    smooth: float = 1.0,
) -> KeynessRow:
    """Compute the full §12 keyness battery for one term."""
    measures = {
        "log_likelihood": keyness_ll(f1, f2, N1, N2),
        "chi_square": keyness_chi2(f1, f2, N1, N2),
        "log_ratio": log_ratio(f1, f2, N1, N2),
        "pct_diff": pct_diff(f1, f2, N1, N2),
        "simple_maths": simple_maths(f1, f2, N1, N2, smooth=smooth),
        # Haldane–Anscombe-corrected so zero cells yield a finite, rankable
        # value instead of ±inf (v1.0.1 linguistics QA).
        "odds_ratio": odds_ratio_haldane(f1, f2, N1, N2),
    }
    return KeynessRow(term=term, f1=f1, f2=f2, N1=N1, N2=N2, measures=measures)


# --------------------------------------------------------------------------- #
# Dispersion
# --------------------------------------------------------------------------- #


def juillands_d(freqs: list[int]) -> float:
    """Juilland's D = 1 − (CV / sqrt(n−1)) across n corpus parts. Range 0–1, higher = more even."""
    n = len(freqs)
    if n < 2:
        return 1.0
    mean = sum(freqs) / n
    if mean == 0:
        return 0.0
    var = sum((f - mean) ** 2 for f in freqs) / n
    sd = math.sqrt(var)
    cv = sd / mean
    return max(0.0, 1 - (cv / math.sqrt(n - 1)))


def gries_dp(observed: list[int], sizes: list[int] | None = None) -> float:
    """Gries' DP = 0.5 · Σ |observed_proportionᵢ − expected_proportionᵢ|  (Gries 2008).

    `observed` is the per-part raw frequencies. Expected proportions are the
    part SIZES as a share of the corpus (sizeᵢ / Σsize) when ``sizes`` is
    given — the correct treatment for corpora of unequal document lengths —
    and fall back to uniform (1/n_parts) when it is not.
    """
    n = len(observed)
    if n == 0:
        return 0.0
    total = sum(observed)
    if total == 0:
        return 0.0
    if sizes is not None:
        size_total = sum(sizes)
        if size_total <= 0 or len(sizes) != n:
            expected = 1.0 / n
        else:
            expected = None  # per-part, computed in the loop below
    else:
        expected = 1.0 / n

    acc = 0.0
    for i, f in enumerate(observed):
        e = (sizes[i] / size_total) if expected is None else expected
        acc += abs((f / total) - e)
    return 0.5 * acc


def gries_dp_norm(observed: list[int], sizes: list[int] | None = None) -> float:
    """DP-norm = DP · n/(n−1)  (Gries 2020) — comparable across different
    numbers of corpus parts. Returns plain DP when n < 2."""
    n = len(observed)
    dp = gries_dp(observed, sizes)
    if n < 2:
        return dp
    return dp * n / (n - 1)


# --------------------------------------------------------------------------- #
# Lexical variation
# --------------------------------------------------------------------------- #


def type_token_ratio(tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    return len(set(tokens)) / len(tokens)


def mattr(tokens: list[str], *, window: int = 50) -> float:
    """Moving-Average TTR (Covington & McFall 2010): mean TTR over every
    consecutive `window`-token window, advanced one token at a time.
    Falls back to raw TTR when the input is shorter than the window.
    O(n) via an incremental window counter."""
    n = len(tokens)
    if n == 0:
        return 0.0
    if n <= window:
        return type_token_ratio(tokens)
    from collections import Counter

    counts: Counter = Counter(tokens[:window])
    ttr_sum = len(counts) / window
    for i in range(window, n):
        old = tokens[i - window]
        counts[old] -= 1
        if counts[old] == 0:
            del counts[old]
        counts[tokens[i]] += 1
        ttr_sum += len(counts) / window
    return ttr_sum / (n - window + 1)


def _mtld_half(tokens: list[str], threshold: float) -> float:
    from collections import Counter

    types: Counter = Counter()
    run_len = 0
    factors = 0.0
    for t in tokens:
        run_len += 1
        types[t] += 1
        if len(types) / run_len <= threshold:
            factors += 1.0
            types = Counter()
            run_len = 0
    if run_len > 0:
        ttr = len(types) / run_len
        # partial factor: linear interpolation of the unfinished factor
        factors += (1.0 - ttr) / (1.0 - threshold)
    return factors


def mtld(tokens: list[str], *, threshold: float = 0.72) -> float:
    """Measure of Textual Lexical Diversity (McCarthy & Jarvis 2010): the
    number of factor-runs (TTR falling to `threshold`) per 100 tokens,
    averaged over the forward and backward pass."""
    if not tokens:
        return 0.0
    forward = _mtld_half(tokens, threshold)
    backward = _mtld_half(list(reversed(tokens)), threshold)
    if forward == 0 or backward == 0:
        return 0.0
    return len(tokens) / ((forward + backward) / 2.0)


def guiraud(tokens: list[str]) -> float:
    """Guiraud's Root TTR = types / √tokens — a size-robust one-number index."""
    n = len(tokens)
    if n == 0:
        return 0.0
    return len(set(tokens)) / math.sqrt(n)


def sttr(tokens: list[str], *, chunk_size: int = 1000) -> float:
    """Standardized TTR — mean TTR over fixed-size consecutive chunks.

    Raw TTR is highly sample-size-sensitive; STTR (Baker 1988 / Richards 1987)
    is the comparably valid default (§8.5). Falls back to raw TTR if the input
    is shorter than one chunk.
    """
    if not tokens:
        return 0.0
    if len(tokens) <= chunk_size:
        return type_token_ratio(tokens)
    chunks = [tokens[i : i + chunk_size] for i in range(0, len(tokens), chunk_size)]
    # drop the trailing short chunk so it doesn't drag the mean (standard practice)
    full = [c for c in chunks if len(c) == chunk_size]
    if not full:
        return type_token_ratio(tokens)
    return sum(type_token_ratio(c) for c in full) / len(full)
