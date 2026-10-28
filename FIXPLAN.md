# CorpusMind v2.0.0 — Statistical & Metadata Remediation Plan

**Status of all 5 reported issues: CONFIRMED** against the code at `v1.2.14` (commit `777e4ee`),
each reproduced numerically from the repo's own `engine/stats/measures.py`.
This plan was produced after (a) reading every affected file end-to-end, (b) running the repo's
own functions against hand-computed standards and a published reference implementation, and
(c) checking the cited literature and the Zenodo/GitHub metadata directly.

**Decisions locked in for this plan** (confirmed with the author):

| Decision | Choice |
| --- | --- |
| Scope | Plan only — implementation-ready specs, exact formulas, golden values, commit order |
| HD-D rollout | **Hard cutover** to the standard 0–1 scale; flagged BREAKING |
| Version | **2.0.0** (statistical outputs change → semver major) |
| Multiple testing | **Benjamini–Hochberg FDR** (q-values per run; raw LL kept) |
| Log Ratio zero cells | **Hardie (2014) 0.5 substitution**, signed values (mirrors the existing `odds_ratio` fix) |
| Deliverable | This file: `FIXPLAN.md` in the repo root |
| DOI | **Concept DOI `10.5281/zenodo.21226649`** in README + CITATION.cff; deposit the new release as a new Zenodo version |
| Manuscript | Full regeneration checklist (§6) |

---

## 0. Evidence base (what was verified, and how)

Every claim was validated by *running the repo's own code* (`python3` against
`engine/stats/measures.py` at `v1.2.14`), comparing against (i) exact combinatorial
re-implementations and (ii) the published `lexical-diversity` PyPI package v0.1.1
(source-verified: its `hdd()` computes `Σ_types (1 − P(X=0)) / 42`).

| # | Issue | Location | Reproduced evidence |
| --- | --- | --- | --- |
| 1 | HD-D on wrong scale | `engine/stats/measures.py:436-473`; documented at `docs/METHODOLOGY.md:508-527`; "documented, not a bug" note in `engine/tests/test_learner.py:25-30` | `hd_d(500 distinct tokens)` = **42.0000** (author's number exactly); standard Σ(1−P₀)/42 = **1.0000** (author's number; published package agrees). On a 2,000-token Zipf sample (seed 42): repo = 28.346, standard = 0.7487 — the ratio is ~38×, not 42×, because the repo *also* aggregates per type differently (Σₓ P(X=x)/x) than the published standard (1−P₀). Flows into CAF (`learner/caf.py:182`) → AI-vs-learner comparator |
| 2 | DP-norm exceeds 1 for unequal parts | `measures.py:331-338` (cites phantom "Gries 2020" — no bibliography entry exists anywhere in the repo) | Parts 20/40/40, item entirely in the smallest part: DP = 0.8, repo DP·n/(n−1) = **1.2000** (author's number exactly), Gries DP/(1−min sᵢ) = **1.0000**. Worse: parts 10/90 → repo = **1.8000**. Live at 3 call sites with real unequal document sizes (`stats/service.py:1780`, `stats/cql_stats.py:276`, `api/visual_corpus.py:649`); `METHODOLOGY.md:249` and `USER_GUIDE_AR.md:217` both claim range [0, 1], which the code violates |
| 3 | LogDice scale mis-taught to LLM | Prompt bug at `engine/ai/assistant.py:96`; the code (`measures.py:55-63`) is **correct** | Code returns 14 + log₂(Dice): max 14.0 at Dice=1 (verified). Prompt says "range typically −15 to 0" — wrong direction entirely |
| 4a | No multiple-testing correction | Prompt at `assistant.py:104` (">3.84 = p<0.05, >6.63 = p<0.01" per word); zero grep hits for Bonferroni/BH/Holm/FDR in `engine/`; no p-values computed anywhere in `stats/` | Thousands of simultaneous per-word tests treated as independent single tests |
| 4b | Log Ratio ±inf on zero cells | `measures.py:149-159` | `log_ratio(f1=0, f2=100, N1=50k, N2=1M)` = −inf; `log_ratio(100, 0, …)` = +inf. While `odds_ratio` in the **same battery** already got a Haldane–Anscombe 0.5 fix in v1.0.1 (`measures.py:186-194`) — inconsistent. Bonus: `±inf` also makes FastAPI emit invalid JSON (`Infinity`) for full-reference-corpus keyness — a latent API bug this fix removes |
| 5 | Metadata drift | `README.md:3,5,37,39,72,536`; `CITATION.cff:48,49,53-54,65-66,69` | README badge **v1.2.11** vs actual **v1.2.14** (git tag + GitHub release 2026-10-20); README **645** backend tests vs **826** `def test_` functions; README DOI badge `…23052753` = Zenodo **version DOI of v1.2.10**; CITATION.cff DOI `…21226650` = Zenodo **version DOI of v0.1.0** (2026-07-06) yet is labelled *"concept DOI — always resolves to the latest version"*, which is false. **True concept DOI: `10.5281/zenodo.21226649`** (both records share conceptrecid 21226649 — verified via Zenodo API). Latest Zenodo deposit is v1.2.10; v1.2.11–14 were never deposited. CITATION.cff also internally drifts (preferred-citation says v1.2.10 / 2026-10-11 vs top-level v1.2.14 / 2026-10-20) |

**Additional gaps found during the sweep** (beyond the 5 reported):

- **A1.** Assistant system prompt has *no* Dispersion or CAF/learner interpretation section —
  the LLM receives DP / DP-norm / Juilland's D / HD-D tool results with zero scale guidance.
- **A2.** README's methods table (`README.md:321-337`) omits HD-D and DP-norm rows entirely,
  despite claiming "every formula … is unit-tested against published worked examples".
- **A3.** `docs/USER_GUIDE.md:411` mis-describes HD-D as *"heterogeneous hapax-based diversity"*.
- **A4.** `test_version_lockstep.py` guards 10 version surfaces but **not** the README release
  badge, the "Current release" line, the README DOI, or the test-count claim — exactly how the
  drift survived.
- **A5.** `test_linguistics_qa.py:52-54` tests DP-norm only on **equal** parts (where both
  normalizations coincide) — that is why the DP-norm bug survived 826 tests.
- **A6.** The AI-vs-learner comparator and CAF battery have *no threshold logic* on HD-D
  (descriptive values + deltas only) — verified, so the HD-D rescale propagates safely with no
  semantic surprises downstream.
- **A7.** `pct_diff` (`measures.py:162-169`) can also return `+inf` on zero cells; the same
  0.5-substitution treatment is recommended for consistency (included in F4, clearly separated
  so it can be skipped).
- **A8.** "CorpMind" (the misspelled title) appears **nowhere** in the repo (case-insensitive),
  in GitHub release titles, or in the current Zenodo record titles. It most likely lives in the
  manuscript draft, the GitHub repo About/description field, or an older Zenodo version record —
  see the manual sweep in §6, step 6.

---

## 1. Principles — how this avoids breaking anything else

1. **Fix formulas in exactly one place.** Every statistical fix lands in
   `engine/stats/measures.py`; all consumers (`stats/service.py`, `stats/cql_stats.py`,
   `learner/caf.py`, `discourse/service.py`, `api/visual_corpus.py`, `export_queue`,
   the AI tools) inherit the correction without signature changes.
2. **No fix without three kinds of tests.** Each fix lands with (a) golden tests whose expected
   values are computed *from the definition* (hand-verifiable), (b) property/bounds tests over
   seeded random inputs, and (c) where possible a cross-check against an independent reference
   implementation embedded in the test file (no new dependencies — the engine is stdlib-only).
3. **Preserve equal-parts behaviour wherever possible.** The corrected DP-norm is *mathematically
   identical* to the old one for equal-sized parts, so every existing equal-parts test keeps
   passing unchanged — the regression surface is strictly the unequal-parts case.
4. **Historical records stay untouched.** `CHANGELOG.md` entries for past releases are never
   edited; corrections are described in the new 2.0.0 entry.
5. **Additive API changes only.** New keyness fields (`p_ll`, `q_bh`) are added alongside
   existing ones; no field is removed or renamed; the web client keeps working without changes.
6. **Every commit green.** The full engine suite must pass at each commit (except the specific
   tests updated in that commit). Fixes, docs, and metadata live in separate commits so any
   regression is bisectable.
7. **Two citation details are flagged for verification at implementation time** (Appendix B) —
   everything else is verified. Be honest in METHODOLOGY.md about what is quoted from where.

---

## 2. Fix specifications

### F1 — HD-D: standard scale (P0, BREAKING)

**Current** (`measures.py:436-473`): per-type sum-score Σₓ P(X=x)/x, total **not** divided by 42
→ 42.0 on 500 all-distinct tokens; ~0.5–0.95 claims in the docstring are wrong by a factor of
~42 and the per-type aggregation also differs from the published standard.

**Target** (McCarthy & Jarvis 2010; identical to the published `lexical-diversity` 0.1.1
implementation — source-verified):

    HD-D = ( Σ_types (1 − P(X_t = 0)) ) / 42 ,
    P(X = 0) = Π_{i=0}^{b−1} (N − f − i) / (N − i)        (exact, stable, no scipy)

The numerator is the expected number of types in a 42-token sample — the exact counterpart of
vocd-D's sampled expectation; dividing by 42 yields the standard 0–1 scale. Range: (0, 1];
500 all-distinct tokens → exactly 1.0.

**Exact replacement** for the function body (keep name, signature, and the `n ≤ sample_size →
TTR` fallback — that degenerate case is correct and tested):

```python
def hd_d(tokens: list[str], *, sample_size: int = 42) -> float:
    """HD-D (McCarthy & Jarvis 2010) — hypergeometric distribution diversity.

    HD-D = (Σ_types (1 − P(X_t = 0))) / 42, where P(X_t = 0) is the hypergeometric
    probability that a type with frequency f never appears in a random 42-token
    sample from N tokens. The sum is the expected number of types in the sample
    (E[V(42)]); dividing by 42 puts the index on the standard 0–1 scale (500
    all-distinct tokens → 1.0). Matches the published `lexical-diversity`
    implementation (Σ(1−P0)/42). Texts ≤ 42 tokens fall back to raw TTR, because
    a 42-token sample then covers the whole text.
    """
    from collections import Counter
    from math import prod

    n = len(tokens)
    if n == 0:
        return 0.0
    b = min(sample_size, n)
    if n <= sample_size:
        return len(set(tokens)) / n
    total = 0.0
    for f in Counter(tokens).values():
        p0 = prod((n - f - i) / (n - i) for i in range(b))
        total += 1.0 - p0
    return total / b
```

Note what this *deletes*: the whole `P(X=x)` recurrence loop. The `P(X=0)` product is kept —
it is numerically exact and overflow-free.

**Callers** — no edits needed: `learner/caf.py:182` (value flows through), CAF deltas
(`caf_delta`) stay consistent, `learner/service.py:44` glossary text stays valid,
`api/learner.py` comment stays valid. Verified there is **no threshold or bound logic** on
HD-D anywhere (A6).

**Tests.**
- `engine/tests/test_learner.py`: **rewrite the module docstring note** (lines ~25-30) — delete
  the "returns the RAW McCarthy–Jarvis sum … documented, not a bug" paragraph and replace with
  the standard-scale note. `test_hd_d_sanity` itself **keeps passing** (short texts still use
  the TTR fallback; the ordering property still holds: 100-distinct → 1.0 vs 50×'a'+50
  distinct → Σ(1−P0) ≈ 22.0 → ≈ 0.524).
- `engine/tests/test_measures.py` — add:
  ```python
  def test_hd_d_standard_scale_500_distinct():
      # Golden: Σ(1−P0) = 500·(42/500) = 42 → HD-D = 1.0
      assert hd_d([f"w{i}" for i in range(500)]) == pytest.approx(1.0, abs=1e-9)

  def test_hd_d_matches_independent_reference():
      # Cross-check the recurrence against exact combinatorics (no scipy):
      toks = ["a"] * 300 + [f"b{i}" for i in range(200)]        # N=500
      N, b = len(toks), 42
      from collections import Counter
      from math import comb
      ref = sum(1 - comb(N - f, b) / comb(N, b)
                for f in Counter(toks).values()) / b
      assert hd_d(toks) == pytest.approx(ref, rel=1e-9)

  def test_hd_d_length_robustness():
      # The measure's raison d'être: near-invariance to text length.
      rng = random.Random(7)
      vocab = [f"w{i}" for i in range(400)]
      text = [rng.choice(vocab) for _ in range(3000)]
      assert abs(hd_d(text) - hd_d(text[:1000])) < 0.05

  def test_hd_d_bounded():
      for seed in range(20):
          rng = random.Random(seed)
          toks = [f"w{rng.randrange(60)}" for _ in range(rng.randrange(50, 800))]
          assert 0.0 < hd_d(toks) <= 1.0
  ```

**Docs.**
- `docs/METHODOLOGY.md:508-527`: replace the ΣₓP(X=x)/x formula with Σ(1−P₀)/42, state range
  (0, 1], add the 500-distinct → 1.0 worked example, keep the recurrence display for P(X=0).
  Cite McCarthy & Jarvis (2010) and **verify the exact equation/page against the paper PDF at
  implementation time** (Appendix B).
- `docs/USER_GUIDE.md:411`: "HD-D (heterogeneous hapax-based diversity)" →
  "HD-D (hypergeometric sampling diversity: expected type density in a 42-token sample, 0–1)".
- `README.md` methods table (§321-337): add row
  `| HD-D (McCarthy & Jarvis 2010) | Lexical diversity | (Σ_types (1 − P(X=0))) / 42, P(X=0) hypergeometric |`.

**Impact statement for the changelog:** every HD-D value changes (≈42× smaller); values are
**not** recoverable by dividing old values by 42 (the aggregation changed too: e.g. Zipf sample
old 28.346 → old/42 = 0.675 but correct = 0.749). Re-run any analysis whose HD-D is reported.

---

### F2 — DP-norm: Gries' normalization for unequal parts (P0, BREAKING)

**Current** (`measures.py:331-338`): `DP_norm = DP · n/(n−1)` — correct **only** for equal-sized
parts (where it reaches exactly 1.0 at maximal concentration); exceeds 1 for unequal parts
(1.2 in the author's case; 1.8 in the 10/90 case). Cites a **phantom reference** ("Gries 2020"
— no bibliography entry exists in the repo).

**Target:** with the repo's ½-scaled DP, the maximum of DP is exactly `1 − min(sᵢ)` (the item
concentrated in the smallest part), so Gries' normalizer bounds the index in [0, 1] for **any**
part sizes:

    DP_norm = DP / (1 − min(sᵢ)),   sᵢ = sizes[i] / Σsizes

For equal parts `min(sᵢ) = 1/n`, so this **reduces exactly to DP·n/(n−1)** — every existing
equal-parts test (`test_linguistics_qa.py:52-54`, `test_measures.py:157-163`) keeps passing
without modification.

**Exact replacement:**

```python
def gries_dp_norm(observed: list[int], sizes: list[int] | None = None) -> float:
    """DP-norm = DP / (1 − min(sᵢ))  (Gries 2008) — bounded in [0, 1] for any
    part sizes, because max DP = 1 − min(sᵢ) (the item concentrated entirely in
    the smallest part). For equal-sized parts (min(sᵢ) = 1/n) this coincides
    with the familiar DP·n/(n−1). Returns plain DP when n < 2."""
    n = len(observed)
    dp = gries_dp(observed, sizes)
    if n < 2:
        return dp
    if sizes is not None and sum(sizes) > 0 and len(sizes) == n:
        s_min = min(sizes) / sum(sizes)
    else:
        s_min = 1.0 / n
    return dp / (1.0 - s_min)
```

(With n ≥ 2 the denominator is strictly positive, so no division-by-zero guard is needed; the
n < 2 early return already exists.)

**Callers** — no edits: `stats/service.py:1780`, `stats/cql_stats.py:276`,
`api/visual_corpus.py:649` (all pass real `sizes` and inherit the fix);
`discourse/service.py:1267` uses plain DP (unaffected); `export_queue/__init__.py:410-411`
prints the corrected value automatically.

**Tests** (add to `test_linguistics_qa.py`, next to the existing ones):

```python
def test_gries_dp_norm_unequal_parts_bounded():
    # Author's reported case: item concentrated in the smallest of 20/40/40 parts.
    assert math.isclose(gries_dp_norm([10, 0, 0], sizes=[20, 40, 40]), 1.0)
    # Extreme unequal case that used to return 1.8.
    assert math.isclose(gries_dp_norm([10, 0], sizes=[10, 90]), 1.0)
    # Below the old breakage threshold: normalizers must agree to bound at 1.
    assert gries_dp_norm([10, 0], sizes=[10, 90]) <= 1.0

def test_gries_dp_norm_proportional_is_zero():
    assert math.isclose(gries_dp_norm([10, 90], sizes=[10, 90]), 0.0, abs_tol=1e-9)

def test_gries_dp_norm_randomized_bounds():
    rng = random.Random(11)
    for _ in range(100):
        n = rng.randrange(2, 8)
        sizes = [rng.randrange(10, 500) for _ in range(n)]
        obs = [rng.randrange(0, 50) for _ in range(n)]
        v = gries_dp_norm(obs, sizes=sizes)
        assert -1e-12 <= v <= 1.0 + 1e-12
```

**Docs.**
- `docs/METHODOLOGY.md:250-252`: replace `DP_norm = DP · n/(n−1) (Gries 2020)` with
  `DP_norm = DP / (1 − min(sᵢ)) (Gries 2008); for equal-sized parts this coincides with
  DP·n/(n−1)`. Cite Gries (2008) and verify page (Appendix B). Keep the existing
  "Range: [0, 1]" line — it becomes true.
- `README.md` methods table: add row
  `| Gries' DP-norm (2008) | Dispersion | DP / (1 − min(sᵢ)); equals DP·n/(n−1) for equal parts |`.
- `web/src/views/AnalysisView.tsx:679` tooltip: "DP-norm makes DP comparable across corpora
  with different numbers *and sizes* of parts (bounded 0–1)."
- `docs/USER_GUIDE_AR.md:217`: the Arabic guide already claims (0→1) — now true; no text change
  needed beyond verifying no DP·n/(n−1) mention exists (grep confirms none).

---

### F3 — Assistant prompt: correct the LogDice scale (P1, prompt-only)

**Current** (`engine/ai/assistant.py:96`):

```
"- LogDice: higher = stronger (range typically -15 to 0).\n"
```

The code (`measures.py:55-63`) is the correct Rychlý (2008) formula — 14 + log₂(Dice), max 14
at Dice = 1 — so **the code stays, the prompt changes**:

```
"- LogDice: 14 + log2(Dice) (Rychly 2008); max 14 when Dice = 1. Interpret: >= 7 strong, "
"4-7 moderate, < 4 weak; very negative values signal accidental co-occurrence.\n"
```

**Tests.** `engine/tests/test_v100_fixes.py` inspects `SYSTEM_PROMPT` content (grounding rules
only — verified not to assert the old string), and `test_ai_chat_endpoint_e2e.py` asserts other
prompt substrings. After editing, run those two files; add one assertion to the v100 suite
pinning the corrected guidance, e.g. `assert "max 14" in prompt` — cheap insurance against the
scale claim drifting again.

---

### F4 — Keyness: BH-FDR correction, exact p-values, Hardie Log Ratio (P1, BREAKING-ish)

Three coordinated changes, all additive at the API level.

**F4.1 Log Ratio — 0.5 substitution for zero cells** (`measures.py:149-159`). Hardie (2014):
substitute 0.5 for a zero frequency instead of returning ±inf. This mirrors the Haldane–Anscombe
0.5 correction `odds_ratio` already received in v1.0.1 (`measures.py:186-194`) and additionally
eliminates a latent bug: `±inf` makes FastAPI emit non-standard JSON (`Infinity`), which breaks
`JSON.parse` clients whenever a full reference corpus contains a word absent from the target.

```python
def log_ratio(f1: int, f2: int, N1: int, N2: int) -> float:
    """Log Ratio = log2( (f1/N1) / (f2/N2) )  (Hardie 2014) — effect size.

    Zero cells use the 0.5 substitution (Hardie 2014; same continuity
    correction odds_ratio applies via Haldane–Anscombe), so the result is
    always finite and rankable. Interpretation: each unit = a doubling of the
    relative-frequency ratio; negative = less frequent in the target."""
    if N1 <= 0 or N2 <= 0:
        return 0.0
    if f1 <= 0 and f2 <= 0:
        return 0.0
    f1s = max(f1, 0.5)
    f2s = max(f2, 0.5)
    return math.log2((f1s / N1) / (f2s / N2))
```

Golden values (verified in this validation): `log_ratio(0, 100, 50_000, 1_000_000)` →
**−3.321928…** (was −inf); `log_ratio(100, 0, 50_000, 1_000_000)` → **11.965784…** (was +inf).
Existing nonzero-cell tests (`test_measures.py:111-116`) keep passing unchanged.

**F4.2 Exact p-values, stdlib-only** (new functions in `measures.py`). LL/G² is asymptotically
χ²₁ under H₀ (Dunning 1993); the engine has no scipy, and none is needed:

```python
def p_value_ll(ll: float) -> float:
    """Survival function of χ²(1): p = erfc(sqrt(ll/2)). Exact to float precision."""
    if ll <= 0:
        return 1.0
    return math.erfc(math.sqrt(ll / 2.0))


def benjamini_hochberg(p_values: list[float]) -> list[float]:
    """BH step-up q-values (Benjamini & Hochberg 1995), order-preserving.

    Returns one q per input, in input order. q_i = min over ranks j >= rank_i
    of (n / j) · p_(j), computed as a running minimum from the largest p down.
    """
    n = len(p_values)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: p_values[i])
    q = [0.0] * n
    running = 1.0
    for rank_from_top, idx in enumerate(reversed(order), start=1):
        rank = n - rank_from_top + 1
        running = min(running, p_values[idx] * n / rank)
        q[idx] = min(1.0, running)
    return q
```

Golden tests: `p_value_ll(3.841458820694124)` ≈ 0.05 (the χ²₁ 95% critical value the prompt
currently misuses); BH on `p = [0.01, 0.04, 0.03, 0.005]` → `q = [0.02, 0.04, 0.04, 0.02]`;
property: `q ≥ p`, `q ∈ (0, 1]`, and q non-decreasing when p are sorted.

**F4.3 Wire into both keyness pipelines** (`stats/service.compute_keyness` at
`service.py:1578+`, and `reference_corpus/keyness_bridge.py:159+`). After per-row computation,
before sorting:

```python
p_vals = [row.measures["log_likelihood"] for row in results]
p_vals = [p_value_ll(ll) if math.isfinite(ll) else 1.0 for ll in p_vals]
q_vals = benjamini_hochberg(p_vals)
for row, p, q in zip(results, p_vals, q_vals):
    row.measures["p_ll"] = round(p, 6)
    row.measures["q_bh"] = round(q, 6)
```

…and append one result-level warning:
`"{n} words tested; log-likelihood thresholds are PER-WORD. Significance after
multiple-testing correction = q_bh < 0.05 (Benjamini–Hochberg FDR); always read alongside an
effect size (log_ratio / pct_diff)."`

Both dicts go into `positive_keywords`/`negative_keywords` rows via the existing
`**r.measures` unpacking — **purely additive**; the web client ignores unknown keys.

**F4.4 Prompt update** (`assistant.py:104`):

```
"- log_likelihood: per-word significance (G² ~ chi2(1)). >3.84 = UNCORRECTED p<0.05 - with "
"thousands of words tested this overstates significance. Use the BH-corrected q_bh field: "
"q_bh < 0.05 = significant after multiple-testing correction.\n"
"- log_ratio: effect size (Hardie 2014), 0.5-substituted for zero cells. Positive = more in "
"target; each unit = a doubling.\n"
```

Also update the "ALWAYS pair significance (LL) with effect size" line to say
"…pair corrected significance (q_bh) with effect size".

**F4.5 (recommended consistency fix, separable)** — `pct_diff` (`measures.py:162-169`) returns
`+inf` when `nf2 = 0` and `nf1 > 0`. Apply the identical `max(f, 0.5)` substitution for
consistency within the battery (and for the same JSON-validity reason). If you prefer to
contain the blast radius, skip F4.5 — but then document in METHODOLOGY.md why %DIFF alone may
still be infinite.

**F4.6 Optional, explicitly deferred by decision:** flooring negative Log Ratio at 0 for
one-sided keyword lists was considered and **not** adopted — signed values are kept (matches
the battery's two-sided design). Revisit only if a UI feature needs one-sided keywords.

**Docs.** `METHODOLOGY.md` keyness section: add BH procedure + exact-p formula + the Hardie 0.5
substitution statement + worked zero-cell example (the golden values above). `README.md`
principle 3 (line 115): append "…significance is reported with Benjamini–Hochberg-corrected
q-values, never per-word thresholds alone."

---

### F5 — Metadata truth-up (P1)

All edits are in *current-state* sections; CHANGELOG history stays untouched.

**README.md**
- Line 3 (DOI badge): `10.5281%2Fzenodo.23052753` → `10.5281%2Fzenodo.21226649` (concept DOI),
  link target likewise.
- Line 5 (release badge): `release-v1.2.11` → `release-v2.0.0`.
- Line 37: "Current release: v1.2.11" → "Current release: v2.0.0".
- Line 39: "Language support (v1.2.11)" → "(v2.0.0)" (sweep all remaining `v1.2.11` strings —
  `grep -n "1\.2\.11" README.md` finds them; keep only genuinely historical mentions, of which
  there are none in the current-state sections).
- Line 72: "645 backend tests" → "800+ backend tests" (a moving target doesn't belong in
  prose; the new lockstep guard below asserts the claimed number never *exceeds* the actual
  count).
- Line 536 (v1.2.11 status note): this is inside a historical status block — verify context;
  if it describes the *current* engine state, update the count and version there too, otherwise
  leave as history.
- Methods table: add the HD-D and DP-norm rows specified in F1/F2.

**CITATION.cff**
- `url:` (line 48) and `identifiers.value` (line 53): → `10.5281/zenodo.21226649`; fix the
  description to "Zenodo concept DOI for CorpusMind — resolves to the latest version" (now
  true).
- `preferred-citation`: version 1.2.10 → 2.0.0, date 2026-10-11 → the 2.0.0 release date, same
  concept DOI. (The existing lockstep test only matches top-level `^version:` — the indented
  preferred-citation version escaped it; fixing both surfaces is part of this commit.)
- Keep `title` as is — verified correct ("CorpusMind", both records confirmed on Zenodo).

**Extend `engine/tests/test_version_lockstep.py`** (the permanent guard — this is what failed
to exist before):

```python
def test_readme_release_badge_matches_engine_version() -> None:
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"release-v([0-9.]+)-blue", readme)
    assert m and m.group(1) == __version__

def test_readme_current_release_line_matches() -> None:
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert f"Current release: v{__version__}" in readme

def test_readme_doi_matches_cff_doi() -> None:
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    cff = (_REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8")
    cff_doi = re.search(r'value:\s*"(10\.[^"]+)"', cff).group(1)
    assert cff_doi in readme.replace("%2F", "/") or \
        cff_doi.replace("/", "%2F") in readme

def test_readme_test_count_not_overstated() -> None:
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"(\d+)\+ backend tests", readme)
    if m:
        actual = sum(
            1 for p in (_ENGINE_ROOT / "tests").glob("test_*.py")
            for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("def test_")
        )
        assert int(m.group(1)) <= actual
```

---

### F6 — Statistical invariant & golden guard suite (P2)

New file `engine/tests/test_measures_invariants.py` — the regression net that would have caught
all four statistical bugs:

1. **Bounds properties** (seeded, ~200 cases): `hd_d ∈ (0, 1]`; `gries_dp_norm ∈ [0, 1]`;
   `log_dice ≤ 14`; `log_ratio` and `pct_diff` finite for any non-negative ints;
   `keyness_ll ≥ 0`; `juillands_d ∈ [0, 1]`; `mattr, ttr, sttr ∈ (0, 1]`; BH `q ≥ p`, `q ≤ 1`.
2. **Golden fixtures**: `engine/tests/data/goldens/measures_v2.json` — a fixed battery of
   ~30 inputs (distinct/Zipf/sparse texts; equal/unequal parts; zero-cell keyness tables) with
   expected outputs generated **once** from the fixed code and cross-checked against the
   independent combinatorial references from this validation. The test asserts equality; any
   future accidental change to a formula fails CI loudly.
3. **Optional cross-implementation check** (skipped by default, no new dependency):
   `pytest.importorskip("lexical_diversity")` → assert `hdd()` agreement on shared fixtures.

---

### F7 — Release protocol v2.0.0 (P2)

Execute in this order (the lockstep suite enforces most of it mechanically):

1. Merge C1–C7 (below); full suite green (`python -m pytest engine/tests`).
2. Version bump commit: `engine/pyproject.toml`, root + web `package.json` **and both
   `package-lock.json`** (root + `packages[""]`), `desktop/src-tauri/tauri.conf.json`,
   `desktop/src-tauri/Cargo.toml`, `shared/package.json`, `web/src/hooks/useEngineVersion.ts`
   (FALLBACK_VERSION), `infra/docker-compose.yml` image tag, both user-guide generator scripts,
   `engine/app/__init__.py` `__version__`, CITATION.cff (top-level + preferred-citation).
   Run the lockstep suite — it fails on any straggler.
3. CHANGELOG: new `## 2.0.0` entry at top with a **BREAKING CHANGES** block: HD-D scale
   (with the 42.0 → 1.0 worked example and the explicit warning that old values are *not*
   recoverable by ÷42), DP-norm formula (1.2/1.8 → 1.0 examples), Log Ratio 0.5 substitution
   (±inf → finite), BH q-values added (`p_ll`, `q_bh`), prompt LogDice correction, README/cff
   DOI corrections. Include a "what to do if you have old reports" paragraph (§6).
4. Tag `v2.0.0` → GitHub release, title "CorpusMind v2.0.0" (spelling matters — this is one of
   the places reviewers look).
5. Zenodo: the release triggers a new **version** deposit under concept `21226649` (Zenodo
   pre-fills from CITATION.cff). Verify the new version DOI appears on the concept page, and
   that the README/cff concept DOI now resolves to it. Note: v1.2.11–v1.2.14 were never
   deposited — optionally deposit them as historical versions afterwards for a complete
   version chain.
6. Docker + installers rebuild via the existing release pipeline.

---

## 3. Commit order (dependency-aware, each commit green)

| Commit | Content | Why this position |
| --- | --- | --- |
| C1 | F1 HD-D fix + tests + METHODOLOGY/USER_GUIDE/README HD-D rows | Foundation; CAF inherits |
| C2 | F2 DP-norm fix + tests + METHODOLOGY/README/tooltip | Independent of C1 |
| C3 | F4.1–F4.2 measures changes (`log_ratio`, `p_value_ll`, `benjamini_hochberg`) + unit tests | Pure functions first |
| C4 | F4.3 service/bridge wiring + warning + API tests | Depends on C3 |
| C5 | F3 + F4.4 prompt edits + prompt-test assertions | Prompts last among code — they describe the fixed behaviour |
| C6 | F5 README + CITATION.cff + lockstep extensions | Metadata describes final state |
| C7 | F6 invariant/golden suite | Guards everything above |
| C8 | F7 version bump + CHANGELOG + tag | Always last |

---

## 4. Risk register

| Risk | Assessment | Mitigation |
| --- | --- | --- |
| HD-D rescale surprises consumers | CAF battery + comparator are descriptive (no thresholds) — verified (A6); UI charts autoscale | §6 manuscript checklist; changelog examples; grep for `hd_d` confirms only pass-through usage |
| DP-norm change alters dispersion rankings | Only where parts are unequal — exactly the broken case; equal-parts results byte-identical | Property tests; changelog examples |
| Log Ratio values change on zero cells only | Nonzero-cell values bit-identical; ±inf JSON bug dies | Golden values in tests |
| BH with huge vocabularies (100k+ words) | O(n log n), pure Python — milliseconds | Benchmark in C7 suite |
| Prompt edits break prompt tests | Only `test_v100_fixes.py` / `test_ai_chat_endpoint_e2e.py` touch the prompt; neither asserts measure ranges | Run both after C5; add corrected-scale assertions |
| Stored results / migrations | No measure values persisted in DB models; exports regenerate on demand | None needed |
| `pct_diff` inconsistency left behind | If F4.5 skipped, %DIFF can still be +inf | Document explicitly in METHODOLOGY.md |
| Citation precision | Two fine-grained citations need a final quote-check (Appendix B) | Flagged in F1/F2/F4 doc steps |

---

## 5. Definition of done

- [ ] `python -m pytest engine/tests` — all green, including the new invariant suite
- [ ] Validation script re-run on the fixed repo: `hd_d(500 distinct) = 1.0`;
      `gries_dp_norm([10,0,0],[20,40,40]) = 1.0`; `log_ratio` finite on zero cells;
      `p_value_ll(3.8415) ≈ 0.05`; BH golden passes
- [ ] `grep -rn "DP·n/(n−1)" --include="*.md"` hits only CHANGELOG history;
      "Gries 2020" gone from current docs; "range typically -15 to 0" gone;
      "645" gone from current-state README; "v1.2.11" gone from current-state README;
      "CorpMind" absent repo-wide
- [ ] New lockstep tests green (README badge, release line, DOI, test count)
- [ ] CITATION.cff validates (`cffconvert --validate` if available) and the concept DOI
      resolves to the new 2.0.0 version record
- [ ] Zenodo shows the new version under concept 21226649
- [ ] §6 manuscript checklist acknowledged

---

## 6. Manuscript regeneration checklist (P0 for the paper)

The four statistical fixes **change published values**. Do not reuse any number produced by
v1.2.14 or earlier.

1. **HD-D** — recompute every reported value. ⚠️ Old values are **not** recoverable by dividing
   by 42 (the per-type aggregation changed too: old 28.346 → old/42 = 0.675, but the correct
   standard value is 0.749 on the same sample). Re-run the engine (v2.0.0) on the same corpora;
   expect values in ~0.4–0.95 for natural text, with 1.0 = maximally diverse.
2. **DP-norm** — recompute every value (not a constant factor; depends on the smallest part
   share). Equal-sized-part results are unchanged; any corpus of unequal documents must be
   rerun. Rankings involving DP-norm may shift.
3. **Keyword lists** — recompute: Log Ratio values change for zero-cell words (±inf → finite),
   and every keyword table now carries `p_ll` and `q_bh`. Words may enter/leave a
   "significant" set: report q_bh < 0.05 (BH-FDR) rather than "LL > 3.84", and update any
   methodology text that quotes the 3.84 threshold to say it is the *per-word* χ²₁ critical
   value, used only descriptively.
4. **LogDice prose** — direction of interpretations is unchanged, but any sentence stating a
   range must say ≤ 14 (max at Dice = 1), not "−15 to 0".
5. **CAF / AI-vs-learner tables and figures** — regenerate (HD-D deltas rescale); no
   interpretation flips expected, but numbers change.
6. **Metadata in the manuscript itself** — global-search the draft for "CorpMind" (title
   typo), confirm the abstract/title both say "CorpusMind", and cite **CorpusMind v2.0.0** with
   the concept DOI `10.5281/zenodo.21226649`. Also check (outside the repo): the GitHub repo
   About/description field (Settings → General), and older Zenodo version records' titles in
   the version chain (current records verified correct).
7. **Methods section** — update formula descriptions to match METHODOLOGY.md post-fix, and add
   one sentence on multiple-testing control (BH-FDR) and the 0.5 substitution for zero cells,
   citing Hardie (2014) and Benjamini & Hochberg (1995).
8. **Figures** — regenerate any axis carrying HD-D or DP-norm values.

---

## Appendix A — Key reproduced numbers (from `scripts/validate_claims.py` run at v1.2.14)

```
CLAIM 1 — HD-D
  repo hd_d(500 distinct)      = 42.0000        standard Σ(1-P0)/42 = 1.0000
  published pkg hdd()          = 1.0000         (independent confirmation)
  2000-token Zipf (seed 42):   repo 28.3460     standard 0.7487     repo/42 0.6749

CLAIM 2 — DP-norm
  parts 20/40/40, item in smallest part:  DP 0.8 → repo 1.2000 → Gries 1.0000
  parts 10/90,  item in smallest part:    DP 0.9 → repo 1.8000 → Gries 1.0000
  equal parts (n=3), all in one part:     repo DP·n/(n−1) = 1.0000 (correct there)

CLAIM 3 — LogDice
  log_dice(Dice=1) = 14.0     (code correct; prompt "-15 to 0" wrong)

CLAIM 4 — Log Ratio / keyness
  log_ratio(0,100,50k,1M)  = -inf → Hardie 0.5-substituted: -3.321928
  log_ratio(100,0,50k,1M)  = +inf → Hardie 0.5-substituted: 11.965784
  Bonferroni/BH/Holm/FDR grep in engine/: zero hits
```

## Appendix B — Two citation details to verify while implementing

Everything else in this plan is verified against code, executed numbers, and fetched sources.
These two details could not be re-confirmed from the primary PDFs during this audit (publisher
sites were unreachable), so do a 2-minute check when editing METHODOLOGY.md:

1. **McCarthy & Jarvis (2010), *Behavior Research Methods* 42(2): 381–392** — quote the exact
   equation number/page for HD-D as Σ(1−P₀)/42. The implemented standard matches the published
   `lexical-diversity` PyPI package (v0.1.1, source-verified: `Σ_types P(at least one
   occurrence in 42)/42`) and the author's stated standard; the repo's old ΣₓP(X=x)/x form is
   not what published implementations compute.
2. **Gries (2008), *IJCL* 13(4): 403–437** — confirm the page where the normalized DP is given
   as DP/(1 − min(sᵢ)) (or equivalently where the n/(n−1) factor appears as the equal-parts
   special case). The repo's "Gries 2020" attribution has **no bibliography entry anywhere in
   the repository** — replace it with the verified citation. The modern statement of DP and its
   normalization is also usefully citable via Sönning's `tlda` package (CRAN), which documents
   the parts-based indices per Gries (2021) and Sönning (2025).

3. **Hardie (2014), "Log Ratio — an informal introduction"** (ESRC CASS, Lancaster) — the
   definition (binary log of the ratio of relative frequencies; each unit = a doubling) was
   confirmed from the archived post. The 0.5 substitution for zero frequencies follows the
   same convention the repo already applies to Odds Ratio (Haldane–Anscombe), and matches
   #LancsBox practice; cite Hardie (2014) for the measure and note the substitution explicitly
   in METHODOLOGY.md.

