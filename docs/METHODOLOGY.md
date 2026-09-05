# CorpusMind Methodology Reference

> Researcher-facing transparency document. Every statistical measure CorpusMind
> computes is defined here, with the exact formula, citation, and the worked
> example used in the unit tests. If a measure is not in this document, it is
> not in the product.
>
> This file is the source of truth for `engine/stats/measures.py`. The Python
> implementations must match the formulas here exactly — a wrong constant is a
> silent, serious validity bug.

## Notation

| Symbol | Meaning |
| --- | --- |
| `O` | Observed joint frequency of node + collocate (within the chosen span) |
| `E` | Expected frequency under independence |
| `R`, `C` | Row / column marginal frequencies (R = node freq, C = collocate freq) |
| `N` | Corpus size (in tokens) |
| `f1`, `N1` | Frequency and size of the **target** corpus (keyness) |
| `f2`, `N2` | Frequency and size of the **reference** corpus (keyness) |
| `f(x, y)` | Joint frequency of x and y |
| `f(x)`, `f(y)` | Marginal frequencies of x and y |

---

## Collocation measures

### Mutual Information (MI) — Church & Hanks (1990)

$$\text{MI} = \log_2\!\left(\frac{O}{E}\right), \quad E = \frac{R \cdot C}{N}$$

- **Use:** collocation strength
- **Sign:** positive when the pair co-occurs more than chance, zero at independence, negative when under-represented
- **Caveat:** unstable for low-frequency pairs (small `O` → large MI). Always pair with a frequency filter and a significance test.

**Reference:** Church, K. W., & Hanks, P. (1990). Word association norms, mutual information, and lexicography. *Computational Linguistics*, 16(1), 22–29.

### T-score

$$T = \frac{O - E}{\sqrt{O}}$$

- **Use:** collocation strength (significance-flavored)
- **Sign:** same as MI; positive above chance, negative below
- **Caveat:** technically a t-statistic without the full degrees-of-freedom machinery; widely used in corpus linguistics as a ranking score. Prefer log-likelihood for formal significance testing.

### Log-likelihood (G²) — Dunning (1993)

$$G^2 = 2 \sum_{ij} O_{ij} \ln\!\left(\frac{O_{ij}}{E_{ij}}\right)$$

computed over the 2×2 contingency table:

|  | Collocate present | Collocate absent | Row total |
|---|---|---|---|
| Node present | `a` | `b` | `a + b` |
| Node absent | `c` | `d` | `c + d` |
| Col total | `a + c` | `b + d` | `a + b + c + d` |

with `E_ij = (row_i_total × col_j_total) / grand_total`.

- **Use:** collocation and keyness significance
- **Distribution:** approximately χ² with 1 degree of freedom
- **Why preferred over χ²:** handles zero cells gracefully (a zero `O_ij` contributes 0 to the sum), which χ² does not

**Reference:** Dunning, T. (1993). Accurate methods for the statistics of surprise and coincidence. *Computational Linguistics*, 19(1), 61–74.

**Worked example (verified, in `tests/test_measures.py`):**
For `a=10, b=990, c=5, d=995` (total = 2000):
- `E_a = E_c = 1000 × 15 / 2000 = 7.5`
- `E_b = E_d = 1000 × 1985 / 2000 = 992.5`
- `G² = 2 × [10·ln(10/7.5) + 990·ln(990/992.5) + 5·ln(5/7.5) + 995·ln(995/992.5)]`
- `G² ≈ 1.7116`

### Dice coefficient

$$\text{Dice} = \frac{2 \cdot f(x, y)}{f(x) + f(y)}$$

- **Use:** collocation strength
- **Range:** [0, 1]
- **Property:** symmetric in x and y

### LogDice — Rychlý (2008)

$$\text{LogDice} = 14 + \log_2\!\left(\frac{2 \cdot f(x, y)}{f(x) + f(y)}\right)$$

- **Use:** collocation strength (the `+14` constant keeps the score in a friendly range for ranking, centered around 0–14 for typical collocations)
- **Property:** symmetric; the standard measure used by Sketch Engine

**Reference:** Rychlý, P. (2008). A lexicographer-friendly association score. *Proceedings of the Second Workshop on Recent Advances in Slavonic Natural Language Processing*.

### Chi-square (χ²)

$$\chi^2 = \sum_{ij} \frac{(O_{ij} - E_{ij})^2}{E_{ij}}$$

over the same 2×2 table as G².

- **Use:** collocation and keyness significance
- **Distribution:** χ² with 1 degree of freedom
- **Caveat:** unreliable when any expected cell count is < 5; prefer G² in that case
- **v1.0.1:** every collocation row now carries `chi2_min_expected` (the smallest
  expected cell count), and the UI surfaces a Cochran-rule warning when it is
  below 5

### Fisher's exact test (v1.0.1)

Two-tailed hypergeometric test on the same 2×2 table: the sum of the
probabilities of all tables (with the same marginals) whose probability is
less than or equal to the observed table's. Computed in log-space via
`lgamma` so large marginals do not overflow.

- **Use:** collocation significance for sparse pairs, where χ²/G² validity
  conditions fail (expected cells < 5)
- **Range:** [0, 1] — a p-value, not a strength score; lower = stronger association
- **Why it matters:** exact test — no distributional assumptions — the standard
  choice for distinctive collexeme analysis (Stefanowitsch & Gries 2003)

**Reference:** Pedersen, T. (1996). Fishing for exactness. *Proceedings of the SAS Users Group*.

### Collocation marginals convention (v1.0.1)

The marginals used by every collocation measure are **whole-corpus
frequencies** (the Sketch Engine / AntConc convention):

- `O` = co-occurrences within the span (same sentence by default)
- `f(x)`, `f(y)` = corpus-wide frequencies of node and collocate
- `N` = corpus size in real tokens

Collocates aggregate under the same case- and diacritic-folding rule as the
node, so `The`/`the` and (Arabic) كِتَاب/كتاب are single rows. Spans may be
asymmetric (`span_left` / `span_right`), and collocates can be filtered by
UPOS prefix or by a stopword list.

### Delta P (ΔP) — Gries (2013); Ellis (2007)

$$\Delta P_{y|x} = P(y \mid x) - P(y \mid \neg x)$$
$$\Delta P_{x|y} = P(x \mid y) - P(x \mid \neg y)$$

with `P(y|x) = f(x,y)/f(x)`, `P(y|¬x) = (f(y) − f(x,y)) / (N − f(x))`, etc.

- **Use:** collocation strength, **directional** — the only measure in the battery that distinguishes "x predicts y" from "y predicts x"
- **Range:** [−1, 1]
- **Why it matters:** many collocations are asymmetric. A near-synonym may strongly predict its hypernym but not vice versa.

**References:**
- Ellis, N. C. (2007). Associative learning in second language acquisition. *Handbook of cognitive linguistics and second language acquisition*.
- Gries, S. Th. (2013). 30-something years of collocations: Some long-standing and some more recent controversies. *Review of Cognitive Linguistics*.

---

## Keyness measures

CorpusMind reports **significance and effect size together** (§4 Principle 3).
A "key" word is never reported as important on frequency-of-occurrence-in-a-
huge-corpus grounds alone.

### Significance tests

**Log-likelihood (G²)** — same formula as above, applied to the 2×2 table
formed by treating the two corpora as rows and the term-vs-other as columns:
`a = f1, b = N1 − f1, c = f2, d = N2 − f2`.

**Chi-square (χ²)** — same 2×2 application.

### Effect size measures

#### Log Ratio — Hardie (2014)

$$\text{Log Ratio} = \log_2\!\left(\frac{f_1 / N_1}{f_2 / N_2}\right)$$

- **Use:** keyness effect size
- **Sign:** positive when over-represented in the target corpus, zero at parity
- **Interpretation:** a value of `+1` means the term is twice as frequent per token in the target corpus

**Reference:** Hardie, A. (2014). A single, transparent measure of keywordness. *ICAME 35*.

#### %DIFF — Gabrielatos & Marchi (2012)

$$\%\text{DIFF} = \frac{\text{norm}_{f1} - \text{norm}_{f2}}{\text{norm}_{f2}} \times 100$$

where `norm_fi = (fi / Ni) × 1,000,000` (per-million-words normalized frequency).

- **Use:** keyness effect size
- **Sign:** same as Log Ratio
- **Interpretation:** percentage difference in normalized frequency

**Reference:** Gabrielatos, C., & Marchi, A. (2012). Keyness: Appropriate metrics and practical issues. *CADS International Conference*.

#### Simple Maths — Kilgarriff (2009)

$$\text{Simple Maths} = \frac{\text{norm}_{f1} + S}{\text{norm}_{f2} + S}$$

with `S` a user-configurable smoothing constant (default 1.0).

- **Use:** combined significance + effect size score
- **Why smoothing:** without it, terms absent from the reference corpus would get an infinite score; smoothing gives them a finite but very high one

**Reference:** Kilgarriff, A. (2009). Simple maths for keywords. *Corpora 2009*.

#### Odds Ratio

$$\text{Odds Ratio} = \frac{f_1 \cdot (N_2 - f_2)}{f_2 \cdot (N_1 - f_1)}$$

- **Use:** keyness effect size
- **Sign:** 1.0 at parity, > 1 when over-represented in target, < 1 when under-represented
- **Property:** the only measure in the battery that is invariant to corpus size (a property of the odds ratio in general)
- **v1.0.1:** when any of the four cells is zero, the **Haldane–Anscombe 0.5
  continuity correction** is applied automatically, so the reported value is
  always finite and rankable (standard practice for sparse tables)

#### Reference-list keyness caveat (v1.0.1)

A bundled **top-N frequency list** is not a full corpus. A target word absent
from the list is *not* absent from the reference population — treating `f2 = 0`
as a real zero produced floods of spurious `±inf` Log Ratio / %DIFF scores.
The bridge therefore (a) **excludes** target words the list does not cover from
the ranking, and (b) returns a machine-readable `warnings` array the UI
displays. For publishable keyness, install and use a full bundled reference
corpus (BNC Baby, BAWE, Leipzig) instead of a top-N list.

---

## Dispersion measures

A plot shows unevenness; a dispersion index quantifies it. **CorpusMind reports
both** (§8.9).

### Juilland's D

$$D = 1 - \frac{CV}{\sqrt{n - 1}}$$

where `CV` is the coefficient of variation (sd / mean) of the term's
frequency across `n` corpus parts.

- **Range:** [0, 1]; 1 = perfectly even distribution, 0 = maximally concentrated
- **Use:** comparing the evenness of a term's distribution across corpus parts

**Reference:** Juilland, A., & Chang-Rodriguez, E. (1964). *Frequency dictionary of Spanish words*. Mouton.

### Gries' DP — Gries (2008)

$$DP = \frac{1}{2} \sum_{i} \left| \text{observed proportion}_i - \text{expected proportion}_i \right|$$

where `observed proportion_i` is the term's frequency in part `i` divided by
its total frequency, and `expected proportion_i` is the part's **share of
corpus size** (`size_i / N`) — the correct treatment for corpora of unequal
document lengths. When part sizes are unavailable it falls back to uniform
`1/n`.

- **Range:** [0, 1]; 0 = perfectly even, 1 = maximally concentrated
- **DP-norm (v1.0.1):** `DP_norm = DP · n/(n−1)` (Gries 2020) is reported
  alongside DP so values are comparable across corpora with different numbers
  of parts
- **Juilland's D caveat:** D assumes roughly equal-sized parts; CorpusMind
  computes it on raw part counts and flags it accordingly — **prefer DP (with
  size weighting) for corpora with heterogeneous document lengths**
- **Range (v1.0.1):** every dispersion result also reports `range` (number of
  documents containing the term) and `range_percent`

**Reference:** Gries, S. Th. (2008). Dispersions and adjusted frequencies in corpora. *International Journal of Corpus Linguistics*, 13(4), 403–437.

---

## Readability (v1.0.1)

### Flesch Reading Ease — Flesch (1948)

$$FRE = 206.835 - 1.015 \cdot ASL - 84.6 \cdot ASW$$

with `ASL` = average sentence length (words/sentence) and `ASW` = average
syllables per word. Higher = easier. Syllables are estimated with the
vowel-group heuristic (silent -e subtracted; consonant+`le` counted as
syllabic; -ed/-es silent except after t/d and sibilants).

### Flesch–Kincaid Grade — Kincaid et al. (1975)

$$FKGL = 0.39 \cdot ASL + 11.8 \cdot ASW - 15.59$$

U.S. school-grade level.

- **Flesch scores are computed for English only** — syllable counting is not
  valid for Arabic script; for non-English corpora they are reported as `null`

### LIX — Björnsson (1968); RIX — Anderson (1983)

$$LIX = \frac{W}{S} + 100 \cdot \frac{L}{W}, \qquad RIX = \frac{L}{S}$$

with `W` = words, `S` = sentences, `L` = long words (> 6 characters).

- **Language-neutral:** LIX/RIX need only word, sentence and long-word counts,
  so they are reported for **every** language including Arabic
- **LIX interpretation:** < 30 very easy · 30–40 easy · 40–50 medium ·
  50–60 difficult · > 60 very difficult

Both are computed per document (`GET /corpora/{id}/documents/stats`) and for
the corpus as a whole (`GET /corpora/{id}/readability`).

## Lexical variation

### Type-Token Ratio (TTR)

$$\text{TTR} = \frac{|\text{types}|}{|\text{tokens}|}$$

- **Caveat:** highly sample-size-sensitive. Larger samples → lower TTR, even
  when the underlying vocabulary distribution is identical. **Not recommended
  for cross-corpus comparison.**

### Standardized TTR (STTR)

$$\text{STTR} = \frac{1}{k} \sum_{j=1}^{k} \text{TTR}(\text{chunk}_j)$$

where each chunk is a fixed-size consecutive slice (default 1000 tokens) and
`k` is the number of full chunks.

- **Use:** the **comparably valid default** for cross-corpus comparison; raw TTR is available but labeled as sample-size-sensitive (§8.5)
- **Trailing short chunk:** dropped from the mean, per standard practice

**Reference:** Baker, J. P. (1988). *Computational approaches to the study of language*. (See also Richards, 1987, on the type-token ratio problem.)

### MATTR — Covington & McFall (2010) — new in v1.0.1

$$\text{MATTR} = \frac{1}{n - w + 1} \sum_{i=1}^{n-w+1} \text{TTR}(\text{window}_i)$$

mean TTR over every consecutive `w`-token window (default 50), advanced one
token at a time; O(n) via an incremental window counter.

- **Use:** size-robust lexical diversity, stable for texts shorter than
  typical STTR chunking needs (falls back to raw TTR when `n ≤ w`)

### MTLD — McCarthy & Jarvis (2010) — new in v1.0.1

The number of sequential factor-runs (TTR falling to 0.72) per token count,
averaged over the forward and backward pass; partial final factors are linearly
interpolated. Higher = more diverse.

### Guiraud's Root TTR — new in v1.0.1

$$\text{Guiraud} = \frac{|\text{types}|}{\sqrt{|\text{tokens}|}}$$

- **Use:** a one-number size-robust index, common in L2/child-language research

All five indices (TTR, STTR, MATTR, MTLD, Guiraud) are returned together in
the frequency result's `lexical_diversity` object.

## Reproducibility

Every result screen in CorpusMind shows which measure(s) and parameters
(window size, smoothing constant, chunk size) produced the number on screen.
The "Export Methods Section" feature (§8.23, Phase 1) auto-drafts a
methodology paragraph citing this document and the engine version that
produced the analysis, for the user to paste into a manuscript.

---

## Phase 2 analytic frameworks

The Phase 2 measures are framework-pinned so results are citable and
comparable across studies:

### Metadiscourse (§8.15)

Hyland, K. (2005). *Metadiscourse: Exploring interaction in writing.*
Continuum.

Categories implemented (10 total):

**Interactive** (how the writer organizes the text):
- Transitions — logical relations between propositions (`however`, `therefore`, `moreover`)
- Frame markers — sequence, topic, discourse stage (`first`, `in conclusion`, `to summarize`)
- Endophoric markers — reference to other parts of the text (`see figure`, `as noted above`)
- Evidentials — attribution to other sources (`according to`, `cited in`)
- Code glosses — reformulation / explanation (`namely`, `in other words`, `e.g.`)

**Interactional** (how the writer involves the reader):
- Hedges — withhold full commitment (`perhaps`, `may`, `appear to`)
- Boosters — emphasize certainty (`clearly`, `undoubtedly`, `in fact`)
- Attitude markers — express writer's attitude (`surprisingly`, `importantly`)
- Self-mentions — first-person pronouns referring to the writer (`I`, `we`, `our`)
- Engagement markers — explicitly address the reader (`consider`, `note that`, `you`)

### Lexical bundles (§8.8)

Biber, D., Johansson, S., Leech, G., Conrad, S., & Finegan, E. (1999).
*Longman grammar of spoken and written English.* Pearson Education.

A lexical bundle is a multi-word sequence that meets BOTH:
1. A minimum frequency per million words (default: 5)
2. A minimum number of distinct texts/speakers (default: 1, but Biber et al.
   recommend ≥3 for spoken corpora and ≥5 for written)

CorpusMind reports both metrics — never raw frequency alone.

### Vocabulary profiling (§8.10)

Coxhead, A. (2000). A new academic word list. *TESOL Quarterly*, 34(2), 213–238.

The Academic Word List (AWL) contains 570 word families selected from a
3.5-million-word academic corpus. CorpusMind ships a starter subset (~60
high-frequency AWL families); Phase 3 will expand to the full 570 + integrate
open frequency corpora for the K1–K5 bands.

### Metaphor detection (§8.17)

Steen, G. J., Dorst, A. G., Herrmann, J. B., Kaal, A. A., Krennmayr, T., &
Pasma, T. (2010). *A method for linguistic metaphor identification: MIPVU.*
John Benjamins.

CorpusMind's metaphor pipeline is **MIPVU-inspired** and runs in three stages:
1. **Candidate generation** (this engine): verbs with abstract subjects — a
   heuristic starter; Phase 3 will add embedding-based comparison.
2. **LLM triage**: the AI Assistant compares contextual vs. basic meaning per
   the MIPVU decision steps (contextual meaning vs. more basic/concrete
   meaning, contrast-but-comprehensible-via-comparison test).
3. **Human verification** (load-bearing): the researcher confirms or rejects
   each candidate before it counts as a confirmed metaphor in any export or
   statistic. Current evidence shows LLMs alone under-perform supervised
   detectors and especially struggle to filter literal false positives — the
   verification step is not optional UI polish, it is load-bearing for
   validity.

### Grammar pattern detection (§8.12)

Detectors are **dependency-parse-driven** (not regex over surface text),
following Universal Dependencies conventions. They handle both UD v2 labels
(`aux:pass`, `acl:relc`) and spaCy legacy labels (`auxpass`, `relcl`) —
`en_core_web_sm` still uses the latter.

Universal Dependencies: <https://universaldependencies.org/>

---

## Phase 3 — Arabic analytic framework

### Arabic morphology (§8.21)

**Backend:** CAMeL Tools (`camel_tools.morphology.analyzer.Analyzer`)
with the `calima-msa-r13` morphology database (Modern Standard Arabic).
Dialect-specific databases are available for Egyptian (`calima-egy-r13`),
Gulf (`calima-glf-01`), and Levantine (`calima-lev-01`).

Pasha, M., Al-Badrashiny, M., Diab, M., El Kholy, A., Eskander, R.,
Habl, N., ... & Roth, R. (2014). *MADAMIRA: A fast, comprehensive tool
for morphological analysis and disambiguation of Arabic.* Proceedings of
LREC 2014.

The `calima-msa-*` databases are the CALIMA reimplementation of the SAMA /
MADAMIRA analysis pipeline, exposed via CAMeL Tools' Python API.

### Root extraction (الجذر) and pattern identification (الوزن)

Arabic morphology is root-and-pattern based. Most Arabic words derive from
a triliteral (three-consonant) root by applying a morphological pattern
that interleaves vowels and affixes among the root consonants.

**Example:**
- Root: **ك.ت.ب** (k-t-b, "write")
- Pattern: **المَ1ْ2َ3َة** → **المَكْتَبَة** ("the library")
- Pattern: **يُ1ْ2ِ3** → **يُكْتِب** ("he writes")
- Pattern: **1ُ2ّا3** → **كُتّاب** ("writers")

CorpusMind extracts the root and pattern for each token using CAMeL Tools'
morphology analyzer. The 1-2-3 placeholders in patterns represent the
three root consonants. This is the standard convention in Arabic
linguistics (Wright 1896; Ryding 2005).

### Buckwalter transliteration

The Buckwalter transliteration maps Arabic script to ASCII Latin
characters. It is a one-to-one, lossless encoding that preserves all
phonological distinctions. Useful for researchers who can't read Arabic
script but need to cite specific word forms in published work.

Buckwalter, T. (2004). *Buckwalter Arabic transliteration.* Linguistic
Data Consortium.

### Dialect identification (§8.21)

Phase 3 ships a heuristic starter (lexicon-based) covering four varieties:
MSA (Modern Standard Arabic), Egyptian, Gulf, and Levantine. Phase 4 will
swap in the full CAMeL `DialectIdentifier` model (274 MB, trained to
differentiate between 25 Arabic city dialects + MSA) behind the same
interface — results stay comparable because the model + version is pinned
per project (§4 Principle 8).

Bouamor, H., Habash, N., Oflazer, K., & Rambow, O. (2019). *The MADAR
Arabic Dialect Corpus and Lexicon.* Proceedings of LREC 2019.

### Register detection

Arabic has a diglossic situation: Classical Arabic (Qoran/Classical),
Modern Standard Arabic (MSA), and the regional dialects. CorpusMind's
register detector distinguishes these three registers using a
lexicon-based heuristic. Phase 4 will integrate a proper classifier.

### Normalization

Three normalization operations are applied (user-controlled):

1. **Alef variants:** أ (alef hamza above), إ (alef hamza below), آ (alef
   madda) → ا (plain alef)
2. **Teh marbuta:** ة → ه
3. **Alef maksura:** ى → ي

These are the standard normalizations used in Arabic computational
linguistics (Sawalha & Atwell 2013; Al-Thubaity 2014). They are
**lossy** — the original forms are preserved alongside the normalized
text for reproducibility.
