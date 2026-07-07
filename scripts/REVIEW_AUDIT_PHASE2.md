# Phase 2 Review Audit

## Verification run

- ✅ 46 tests passing (23 stats + 9 Phase 1 API + 14 Phase 2 API)
- ✅ Web typecheck clean
- ✅ Web PWA builds
- ✅ Ruff clean (0 errors)
- ✅ No TODO/FIXME/HACK markers
- ✅ No `datetime.utcnow()` (deprecated) — all using `datetime.now(timezone.utc)`
- ✅ No debug `print()` calls
- ✅ No unused variables (F841)

## Spec compliance — Phase 2 (§8.8, §8.10–8.13, §8.15, §8.17, §8.18)

| § | Feature | Status | Notes |
|---|---|---|---|
| 8.8 | N-grams + lexical bundles | ✅ | Frequency-and-range criterion implemented (Biber et al.); both min_freq AND min_range required; `test_ngrams_respects_min_range` proves the gate works |
| 8.10 | Vocabulary profiling | ✅ | K1/K2-K9/AWL/Off-list bands; starter AWL subset (Coxhead 2000); rare words + academic words reported; CC-0 wordlist, EVP not bundled (§13.5 compliant) |
| 8.11 | POS analysis | ✅ | Distribution + POS n-grams (1–5); `test_pos_bigrams` proves DET NOUN pattern detected |
| 8.12 | Grammar analysis | ✅ | 6 dependency-driven detectors (passive, modal, negation, relative_clause, complex_np, tense); handles both UD v2 + spaCy legacy labels; `test_grammar_passive/modal/negation` all pass |
| 8.13 | Dependency analysis | ✅ | Thin queries over existing parses; governor-dependent pairs for any UD relation; example evidence IDs returned |
| 8.15 | Discourse (Hyland) | ✅ | All 10 categories (5 interactive + 5 interactional) match METHODOLOGY doc; taxonomy pinned ("Hyland 2005"); `test_discourse_analysis` finds transitions + code_glosses |
| 8.17 | Metaphor candidates | ✅ | MIPVU-inspired pipeline; candidate generation + LLM triage + human verification gate (load-bearing per §8.17 +ADD); `verified_count: 0` until human confirms; `test_metaphor_candidates` proves evidence_id stable |
| 8.18 | Sentiment | ✅ | Lexicon-based per-sentence; positive/negative/neutral + timeline; `test_sentiment` proves all 3 categories detected |

## Grounded-AI tool surface

14 tools registered (Phase 1: 6, Phase 2: 8, plus ping). All return JSON-serializable
dicts with stable evidence IDs. The `grounded: bool` flag flips true whenever at
least one tool is called — load-bearing §11.1 contract intact.

## Reproducibility

- Every Phase 2 result includes its parameters (window, min_freq, min_range, n,
  patterns, relation, rare_threshold).
- Hyland, Biber, Coxhead, and Steen (MIPVU) citations all present in
  `docs/METHODOLOGY.md` and in the code docstrings.

## Issues found

None. Phase 2 is accurate and consistent with the spec. Ready to proceed to Phase 3.
