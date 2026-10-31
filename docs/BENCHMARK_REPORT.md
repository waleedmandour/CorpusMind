# CorpusMind Benchmarking Report — frozen-row battery (2026-10-31)

Freeze SHA: `ee42bfa` (`ee42bfab72291072b191ebb4c7d77ec03bb1f94d`, = main @
"docs(bench): reframe the Gemini reference row as free-tier-by-design (#49)").
Frozen refs: `bench/freeze-1` (Gemini crawl), `bench/freeze-1-local` (local
rows), `bench/freeze-1-seg` (segmentation). sha256 `engine/eval/questions.py`
= `b521cbb1…`, `engine/eval/data/gold/grounding_gold.json` = `480f5230…`.
Gold-diff gate: GREEN at the freeze SHA (run 41173011756: clean=true,
diffs=[], 80 frozen = 80 rebuilt). Bank: 80 questions, ids G-001..G-080.

During the whole battery the engine/gold/bank/scorer/prompt files were
untouched at the freeze SHA (verified rule: `git diff ee42bfa -- engine
':!engine/eval'` is empty on every branch used for addendum work).

## 1. Segmentation row (AraSEG, canonical)

Run 41173011756 on `bench/freeze-1-seg` @ ee42bfa (seg_limit=20 → superseded
by the A4 222-doc rerun for the extrinsic view; intrinsic identical).

Intrinsic (222 dev docs, boundary P/R/F1 vs AraSEG dev splits):

| condition | micro-F1 | micro-P | micro-R | macro-F1 | perfect docs |
|---|---|---|---|---|---|
| PA | 0.7115 | 0.8748 | 0.5996 | 0.6705 | 10 |
| NP | 0.5572 | 0.8326 | 0.4187 | 0.5469 | 3 |

Extrinsic (all 222 dev docs, engine vs gold segmentation through the real
engine; deltas are GOLD MINUS ENGINE — positive = engine produced fewer):

| measure | PA | NP |
|---|---|---|
| boundary errors | 6,313 | 8,641 |
| delta sentences | +5,291 | +7,593 |
| engine/gold sentence count | 0.616 | 0.449 |
| CAF delta mean sentence length | −62.71 | −88.27 |
| sentiment flips (+/−) | +54/−99 | +68/−122 |
| collocation / n-gram / CQL deltas | 0 | 0 |

Reading: the engine's sentence-splitting under-segments Arabic sharply
(fewer, longer sentences than gold), which inflates CAF sentence length and
shifts sentiment; collocational/n-gram/CQL statistics are robust to the
segmentation difference at these settings. The 20-doc extrinsic view (run
41173011756) is superseded by the 222-doc numbers above. Test split NOT run
(user decision).

## 2. Calibration of the segmentation evaluator (A5)

`engine/eval/calibration_sentence.py` (bench/extra-1) reproduces Table 4 of
arXiv:2606.08025 (dev) within 0.21 F1: PA punkt 65.18/65.2, pysbd
63.31/63.1, spacy 67.29/67.3; NP punkt 52.32/52.3, pysbd 52.05/52.1, spacy
54.31/54.3. Root cause of the initial PA mismatch (12–13 F1): punkt /
sentencizer ignore bare newlines while the paper's PA protocol counts
paragraph breaks; NP matched with no change. No evaluator or split change
was needed. Raw calib JSONs: `bench-state/artifacts/calib_{PA,NP}.json`.

## 3. Performance row (production Arabic pipeline, snapshot corpus)

From the battery's perf job (median over repetitions, CV%): analyze path
2,687–2,709 tok/s across 20k/100k/250k-token inputs (CV 0.3–1.3%); dialect
ID ≈ 96.6k–98.8k tok/s; cold engine load 4.0 s. Steady-state morphology
throughput is on par with CAMeL-Tools cost bounds and is reported with CV%
because CI runners are shared.

## 4. Local grounding rows (Ollama, A3 triples)

Each config: full 80-question bank, 3 independent runs on
`bench/freeze-1-local` @ ee42bfa, scored offline against the frozen gold.

| config | runs (pass rate) | mean pass | runs (halluc. rate) | mean halluc. | verdict flips |
|---|---|---|---|---|---|
| qwen2.5:1.5b | 0.1625 / 0.15 / 0.15 | **0.1542** | 0.625 / 0.6875 / 0.675 | **0.6625** | 16/80 (20%) |
| qwen2.5:3b | 0.075 / 0.075 / 0.0625 | **0.0708** | 0.3625 / 0.3875 / 0.425 | **0.3917** | 24/80 (30%) |
| qwen2.5:7b | probe only (5 q) | — | — | — | — |

Verdict distributions (across runs): 1.5b PASS 12–13, MISSING_NUMBER 11–14,
HALLUCINATED 39–44, TRAP_FAILURE 13–14; 3b PASS 5–6, MISSING_NUMBER 31–37,
HALLUCINATED 23–30, TRAP_FAILURE 14.

Reading: (a) both models are far below any usable operating point — at most
13/80 questions answered passably; (b) 3b fails *safer* than 1.5b (shifts
HALLUCINATED → MISSING_NUMBER: mean hallucination 0.39 vs 0.66) but passes
less (0.0708 vs 0.1542); (c) verdict flips across identical re-runs (16–24
of 80) show single-question instability, concentrated in
HALLUCINATED↔MISSING_NUMBER, with no systematic direction — single-run
grounding scores for small local models carry a ±2.5–5 pp noise band.

7b: timing probe (run 41206910830, 5 questions) measured mean 271.5 s/q →
full-80 projection 362 min > the 330-min CI runner cap → **does not fit**;
per the pre-registered rule the 7b row is **pending user-run** with a
one-command runbook in `engine/eval/README.md` (bench/extra-1). Probe
verdicts (diagnostic only): MISSING_NUMBER×2, HALLUCINATED×2,
TRAP_FAILURE×1.

Superseded rows: the afce8fe 1.5b row (run 41028985957, pass 0.1375 /
halluc 0.65) predates the #43/#44 re-freeze; its delta vs the current row
reflects engine+gold changes together, not engine effect alone.

## 5. Gemini free-tier reference row (by design, IN PROGRESS)

The reference row is free-tier by design: gemini-3.8-flash, 20 requests/day
per project (resets midnight Pacific), crawled as a multi-day drip
(morning slice ≤16 ids + drip ≤4 ids, never >20/day).

- Banked reusable for the freeze row: **5/80** — G-001, G-002 (clean runs on
  the freeze lineage), G-004, G-040, G-073 (REUSED from the Oct-30 probe run
  41051082943; reuse disclosed — the rule now excludes engine/tests, and
  `git diff 9c272b8..ee42bfa -- engine shared reference-data ':!engine/tests'`
  is empty). Caveat: the three reused answers scored under the PRE-freeze
  gold; G-004 was an honest-trap fail and its freeze-row score is reported
  as-is.
- Slice-1 (2026-10-31, first full free-tier day): 16 ids attempted, **0
  clean** — 15× 429-class transport failures + 1× deadline. A fresh 20/day
  pool would have allowed ~16 clean: the reset/quota model is NOT holding
  (day-2 evidence; Oct-30 accounting was also inconsistent — 79×429 at
  12:27Z then a clean G-002 at 20:06Z the same Pacific day).
- Off-spec probe attempts (Oct-30 evening, disclosed, 0 clean answers):
  flash-lite (41125306050), pro (41127495897), flash (41129889514,
  41134947351) — all "Model call failed: [cloud] chat request failed".
- Duplicate asks to disclose: G-004 2× clean, G-040 2× clean, G-073 1 dirty
  + 1 clean (none double-banked; the freeze-row answer is the earliest
  freeze-clean one).
- Status at report time: the crawl is OPTIONAL for this report (A8); with
  the quota anomaly unresolved the row is recorded as IN PROGRESS with the
  probe runs as incident evidence. Scheduled tasks were removed at report
  time (see §8); resuming the row later needs only the dispatch runbook in
  `bench-state/scripts/dispatch_crawl.sh` and the parameters in §2 of
  STATE.md (branch `bench/state`, path `bench-state/STATE.md`).

## 6. Stats-parity check (A6)

`engine/eval/parity_stats.py` (bench/extra-1) compares the engine's measures
with scipy / statsmodels / lexicalrichness on ONE shared corpus set (the 9
snapshot texts, 29–369 tokens each) with ONE shared tokenizer handed to both
sides. Result (max abs / max rel deviation across corpora):

| measure | engine vs reference | max abs dev | max rel dev |
|---|---|---|---|
| TTR | lexicalrichness | 0 | 0 |
| MATTR(50) | lexicalrichness | 2.0e-15 | 2.4e-15 |
| STTR(1000) | lexicalrichness | 0 | 0 |
| HD-D(42) | lexicalrichness | 1.4e-15 | 1.7e-15 |
| Guiraud RTTR | lexicalrichness | 0 | 0 |
| Pearson χ² (no Yates) | scipy | 0 | 0 |
| Dunning G² | scipy | 0 | 0 |
| Odds ratio (uncorrected) | statsmodels | 0 | 0 |
| MTLD(0.72) | lexicalrichness | 1.3777 | 2.87% |

MTLD is the only gap and it is a disclosed AGGREGATION CONVENTION, not a bug:
engine = len(tokens)/mean(forward, backward factor counts); LR = mean of the
two directional MTLD scores (the McCarthy & Jarvis 2010 published form);
equal iff both passes find the same factor count. Convention checks made
along the way (A6 rule): LR 0.5.x default preprocessing (lowercase, strip
punct/digits) was pinned away to preserve the shared-token premise; the
engine's odds_ratio takes (f1, f2, N1, N2) rather than raw 2×2 cells; LR
names the HD-D parameter `draws`; corpora shorter than a window are excluded
on the LR side (LR raises, engine falls back). Raw report:
`bench-state/artifacts/a6_parity.json`.

## 7. Scale benchmark (A7) — ingest / KWIC / keyness at 1M and 10M tokens

`scripts/benchmark_scale.py` on `bench/scale-1` (@ 9dd65d2, engine-diff rule
empty), run 41203959363, one matrix leg per size on a fresh SQLite file,
CI runner (ubuntu-latest), full spaCy `en_core_web_sm` 3.8.0 pipeline
(degraded=false — tagger/lemmatizer/parser active), 350-min job cap.
Corpus: SYNTHETIC, cycled frozen en-snapshot sentences (~234 types,
~1,000 tok/doc) — repetitive-text steady-state, stated by design.

| phase | 1,000,050 tokens | 10,000,547 tokens | scaling |
|---|---|---|---|
| ingest wall | 348.6 s (3,013 tok/s) | 4,721.3 s (2,129 tok/s) | ~30% throughput drop, sublinear |
| KWIC "the" @limit 400 | 5.87 s (75,632 hits) | 70.25 s (756,340 hits) | ~12× for 10× tokens+index |
| KWIC "goal" @limit 400 | 5.59 s (16,806 hits) | 62.32 s (168,078 hits) | ~11× |
| KWIC ceiling probe "the" @1000 | 14.21 s | 166.6 s | OK at both scales (borderline) |
| keyness (vs 50k reference) | 0.69 s | 8.22 s | linear |
| DB size | 470 MB | 4.52 GB | linear |
| peak RSS (process max) | 238 MiB | 287 MiB | **flat** |

Findings:
1. The storage paths scale to 10M tokens on a standard runner; peak memory
   is corpus-size independent (the pipeline streams) — no OOM risk.
2. ENGINE SCALE CEILING (reported, not patched — engine frozen for the
   rows): the word-level KWIC context fetch builds ONE un-chunked `or_()`
   over every matched sentence; SQLite's expression-depth limit (1000) is
   crossed when a limit-1000 query matches ≳950 distinct sentences. The
   phrase path already chunks at 400; the word-level path should chunk the
   same way. All envelope measurements (limit=400) are unaffected.

## 8. Provenance, anomalies, and disclosures

- Freeze/gold: gold-diff gate GREEN at ee42bfa (runs 41163039515 and
  41173011756, clean=true, diffs=[]). Snapshot branches pushed for every
  completed run; the workflow's automatic snapshot-PR step silently failed
  (known anomaly), so manual data-only PRs were opened: #50 (seg canonical),
  #51 (A4 222-doc), #52–#56 (local rows). Merge is the maintainer's call.
- Quota model: the free-tier Gemini quota/reset model in the original brief
  does NOT hold (§5); treat slices as adaptive and ≤20/day regardless.
- Off-spec model attempts on Oct-30 (flash-lite, pro): 0 clean answers,
  quota tail consumed, disclosed above.
- The Oct-30 20:42–21:58Z dispatch runs (4) were not in the original brief;
  all 0 clean, two off-spec models, no bank impact.
- Brief-vs-actual: canonical seg snapshot was said to be @ 06de47b; the
  actual run is @ 57be77f, and is superseded by §1 either way.
- Scheduled tasks and the repository secret used by them were removed at
  report time (cleanup step T6); the benchmark rows above were produced
  before removal and are unaffected.
- Addendum sequencing note: A6 was executed early (in parallel with the A3
  local chain) because it is CPU-local work on a bench ref with zero contact
  with any frozen row; recorded in STATE.md §9.
