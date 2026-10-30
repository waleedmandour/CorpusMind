# Benchmark Score Improvement Plan — Arabic sentence segmentation + grounding fidelity

**Date:** 2026-10-29 · **Updated:** 2026-10-30 (Tier-1 measured; estimates corrected)
**Status:** Tier-1 rules LANDED (v2.0.1 + #39); Tier-2 is the only route to the 0.9s
**Inputs:** the AraSEG paper's own results table (Elkholy et al., arXiv:2606.08025,
Table 4 — same dev splits, same protocol; the paper is an arXiv preprint, data from
the AraSEG shared-task release at ArabicNLP 2026 @ EMNLP 2026); the measured error
budget; the canonical CI snapshot (run 40970859593 + #39's CI reproduction).

## 1. Where we honestly stand (fair comparison)

The paper's Dev-set **PA** F1 (macro, per-document), same data, same protocol:

| System (rule-based, offline) | PA F1 | NP F1 |
|---|---|---|
| Paragraph-breaks-only baseline | 45.2 | — |
| PySBD | 63.1 | 52.1 |
| Ersatz | 64.7 | 51.6 |
| NLTK Punkt | 65.2 | 52.3 |
| **CorpusMind rule splitter (Tier-1, measured)** | **67.1** | **54.7** |
| ENS_Pnx+Lexical | 67.3 | 55.4 |
| SpaCy sentencizer | 67.3 | 54.3 |
| SaT (wtpsplit, EMNLP 2024) | 66.9 | 60.9 |
| LLMs (best: Qwen2.5-72B) | 81.2 | 69.3 |
| Dependency-parser models (Flat Orig Deprel) | 94.7 | 91.0 |
| **CAMeLBERT (paper's best, released)** | **95.6** | **93.4** |

Row values are the measured macro scores: **PA 0.6705, NP 0.5469** (micro PA 0.7115 /
NP 0.5572; precision PA 0.877; CI reproduced the local numbers exactly on #39). The
earlier "corrected 64.8 / 52.9" row and the 0.107 figure were evaluation artifacts and
are retired; the manuscript should cite the canonical snapshot (run 40970859593) plus
the #39 CI run.

Reading: with Tier-1 landed, the rule splitter is now **above every classical
baseline on both conditions** (Punkt 65.2/52.3, SpaCy 67.3/54.3, PySBD 63.1/52.1,
Ersatz 64.7/51.6), within noise of SaT on PA (66.9) and ~6 points under SaT on NP
(60.9) — respectable for a zero-dependency, instant, offline component. The gap that
matters is to the learned models (95.6), and that gap has a documented, licence-clean
path (§3) — subject to the licence caveat in the data statement: the dataset cards
state MIT, while the paper describes BAREC-derived material under CC BY-SA 4.0.

## 2. Tier 1 — principled rule fixes (LANDED; measured, not estimated)

**Why the original "PA 0.67 → ~0.85" estimate was withdrawn:** it was arithmetically
impossible. ~79% of the misses (3,880 of 4,926 FN) have no punctuation cue for a
rule to fire on, so no rule recall gain can exceed ~21% of FN. With the measured
precision 0.877 and recall 0.595, F1 is 0.709; even adding the §4 verse-marker rule
(+1,046 FN at near-zero precision cost) reaches only ≈ 0.77. **The rules are
essentially done; Tier-2 is the only route to the 0.9s.**

Landed outcome (canonical evaluator): PA micro-F1 0.673 → 0.709 (v2.0.1) → 0.7115
(#39 quote-guard regression fix); precision 0.736 → 0.877; FP 2,894 → 1,081; NP
0.528 → 0.5572. Rules shipped: terminal-run collapse, semicolon demotion,
quote-parity guard (same-line closer; ASCII `'` never guards).

1. ~~**Collapse consecutive terminal runs into ONE boundary.**~~ **Landed** — dominant
   FP class (spaced ellipsis tokens, masked words) fixed; also a real quality fix for
   KWIC context, collocation windows and per-sentence sentiment.
2. ~~**Demote `؛` (Arabic semicolon) from terminal.**~~ **Landed** — gold ends a
   sentence at only 90/349 `؛` (26%); MSA norms treat `؛` as clause-level (Yagi,
   "Is Arabic punctuation rule-governed?", Cogent Arts & Humanities 2024).
3. ~~**Quote-parity guard.**~~ **Landed** — v2.0.1 + the #39 same-line-closer fix;
   stray self-paired quotes (`Qur'an`, `27"`) stay literal.

Sequencing note (reworded 2026-10-30): these are engine semantics changes → they
shift `sentence_idx` for every Arabic consumer (KWIC context, collocations, CQL
`within sentence`, sentiment, CAF, alignment). They landed as semver-minor with unit
tests per rule, the full AraSEG battery re-run, and a CHANGELOG note that published
sentence counts change slightly. Sentence-segmentation-independent statistical gold
values (frequency/dispersion/keyness; DP uses equal parts, not sentences) are
unaffected by construction — **but that is not evidence that the frozen grounding
gold is unaffected**: the Arabic sentence-scoped questions (G-044, G-056, G-074, and
possibly G-002) recompute sentence-scoped counts and may shift. Only a **full
80-question gold diff in CI** establishes this. It must run (and pass, or the diff be
reviewed and the gold re-frozen as a reviewable event) **before any grounding re-run,
and again after any further splitter change**.

## 3. Tier 2 — pluggable neural segmenter as an Arabic "data pack" (the path to ~0.95)

The paper itself releases the winning system: **`MBZUAI/sentseg-camelbert-{PA,NP,NoPnx-PA,NoPnx-NP}`
(MIT licence per the model cards)** — a fine-tuned CAMeLBERT doing binary boundary
classification; 95.6 PA / 93.4 NP dev F1; and the paper's headline finding is that
*lightweight encoders beat even GPT-5.5-class LLMs at the hardest conditions*. Two
implementation options:

- **Option A (recommended): CAMeLBERT sentseg data pack.** Follows the app's existing
  "Arabic data pack" installer pattern (pinned download, size+sha256 verification,
  offline inference, graceful fallback to the rule splitter when the pack is absent —
  exactly like the CAMeL morphology DB). ~150–550 MB on disk; CPU inference is fine
  for ingest-time batch use (papers report real-time speeds on CPU for BERT-base).
  Ingest chooses: pack present → neural boundaries; absent → rules. The benchmark
  battery then reports **both** tiers, as it already distinguishes engine vs gold
  segmentation.
- **Option B: wtpsplit SaT (`sat-3l-sm`, MIT, EMNLP 2024).** One model covers Arabic
  *and* the English/general corpora (85 languages), punctuation-agnostic by
  pretraining — solves the NoPnx ceiling too. Heavier and it would also change
  English segmentation semantics; consider for a later cross-language parity release.

Design guardrails: sentence_idx provenance must be recorded per corpus version
(`segmenter: rules|camelbert`), so a reviewer can reproduce any published number; the
grounding harness should get a trap question exposing which segmenter produced a
given count.

## 4. Tier 3 — classical/Quranic register (targets the 1,046 verse-marker FN)

Gold boundaries after `)` ayah-number markers are a distinct, documented error class
(the paper's error analysis lists "verse boundaries" even for CAMeLBERT). A
register-aware rule — detect `( n )` / `(n)` verse-marker sequences (or ﴿﴾ ornate
brackets) and treat the closing marker as a boundary — is corpus-motivated rather
than benchmark-hacked: the Quranic register is a first-class CorpusMind use case
(quranic-arabic reference corpus ships in `reference-data/`). Expected: +1,046 PA
recall at near-zero precision cost — but note the §2 arithmetic: even with it, rule
F1 tops out around 0.77, so decide by use-case value (Quranic ingest), not by the
benchmark. Keep it behind the same register-detection flag the engine already uses
for classical texts.

## 5. Grounding-fidelity benchmark improvements (the other citable battery)

The 80-question bank's build-time audit documented tool-coverage gaps that cap the
grounding score by construction (honest `no_tool` traps):

- `get_frequency` exposes **STTR only** — add TTR, MATTR, MTLD, Guiraud, and the
  v2.0.0 HD-D so the assistant can quote the corrected statistic.
- `get_dispersion` exposes DP + Juilland's D but **not DP-norm or range** — the
  Lijffijt–Gries corrected DP-norm is invisible to the assistant.
- No bundled-reference keyness tool; no readability tool.
- Then re-freeze the gold (a reviewable event per the harness discipline) and re-run
  the battery — **primary row: a local Ollama model (no provider quota, fits the
  local-first pitch); reference row: Gemini with a PAID key** (the free tier's 20
  requests/day for gemini-3.8-flash cannot cover the ~160+ calls the full bank
  needs).

## 6. What NOT to chase

- **Throughput (2,674 tok/s steady-state)** is not a "low score": it is on par with
  CAMeL-Tools morphology cost bounds, projects to ~6 min/M tokens, and the battery
  already reports CV% < 1%. Manuscript framing: relative costs (morphology vs
  dialect-ID ≈ 36×) matter more than absolutes on shared runners.
- **NP/NoPnx conditions for rules** are a documented ceiling (paper agrees); don't
  tune rules against them — that's what Tier 2 solves.

## 7. Where the work stands (order, updated 2026-10-30)

1. ~~Tier 1 rules + battery re-run~~ — **DONE** (v2.0.1; #39 CI-reproduced PA
   0.7115 / NP 0.5572).
2. ~~Canonical manuscript snapshot~~ — **DONE** (run 40970859593, snapshot v3; #37).
   Manuscript cites the **version DOI of the release evaluated**:
   `10.5281/zenodo.23785435` (v2.0.1); concept DOI `10.5281/zenodo.23216073`.
3. ~~**Full gold diff in CI**~~ — **DONE, and it earned its keep** (#42 gate;
   #43 re-freeze; #44 second round): the first run found the frozen gold BOTH
   stale (G-002 19→18, G-056 16→15) and unstable (keyness/cue hash order);
   a fresh-boot re-run then exposed a second entropy source (tied rows and
   example caps inheriting the per-boot `document_id` hex order — G-037's
   `top 2-gram` was boot luck). Deterministic tie-breaks + re-frozen gold;
   gate green on two fresh-boot rebuilds. The gate runs on every PR touching
   eval/splitter paths.
4. ~~**Grounding rows**~~ — **DONE for the primary row** (#41 flattening fix +
   mock regression test, verified against real Gemini in the probe; #44
   determinism). **Primary (local-first) row recorded**: Ollama `qwen2.5:1.5b`,
   full bank, pass_rate **0.1375** (CI95 0.0625–0.2125), hallucination 0.65 —
   see `benchmarks/README.md` results snapshots. **Gemini full row: pending a
   PAID key** (free tier 20 RPD < the ~160+ calls the bank needs); the probe
   row stands in for the cloud path until then.
5. Tier 2 CAMeLBERT data pack (installer + ingest switch + battery "neural" tier).
6. Tier 3 verse-marker rule behind register detection (use-case motivated; see §4).
7. ~~**Release storage cleanup**~~ — **APPLIED** (2026-10-30, after #40 merged):
   fresh dry-run matched `docs/release_retirement_manifest.csv` exactly (440
   rows), then 302 installers (67.9 GB) deleted across 49 releases, 0
   failures; superseded banners added. Verified post-state: only the 12
   v2.0.0/v2.0.1 installers remain; 138 kept assets (guides, web zips,
   checksums) and `reference-mirrors-v1` untouched.
8. Grounding tool-coverage pass (§5) + gold re-freeze + provider-in-the-loop runs.
