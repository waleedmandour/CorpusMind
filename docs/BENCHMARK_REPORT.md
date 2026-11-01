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
| CAF delta mean sentence length (per-doc deltas summed) | −62.71 | −88.27 |
| sentiment flips (+/−) | +54/−99 | +68/−122 |
| collocation / n-gram / CQL deltas (per-doc recording, superseded) | 0 | 0 |

**F2 correction (2026-10-31, pooled re-run).** The recorded zeros for
collocation / n-gram / CQL in the row above are an artifact of the per-doc
design, NOT evidence of robustness, and partly a response-key bug: the eval
script read `top_collocates`/`top_ngrams` while the REST endpoints return
`rows`, so rows were recorded as empty even when the engine returned a full
table; and the single-term CQL pattern ("في" within sentence) cannot show a
delta by construction (every occurrence lies inside SOME sentence under both
segmentations). The re-run (`engine/eval/segmentation_downstream.py --pool`
on bench/extra-1, commit 76454a0) pools all 222 docs into ONE engine vs ONE
gold corpus per condition (byte-identical AraSEG dev parquets, sha256
verified vs the frozen runs), uses realistic thresholds (min_freq ≥ 5) and
data-driven TWO-TOKEN CQL sequences. Results (gold minus engine; the pooled
corpus reproduces the frozen per-doc totals exactly: boundary errors
6,313/8,641, delta sentences +5,291/+7,593, sentiment +54/−99 and +68/−122):

| pooled measure (222 docs, min_freq ≥ 5) | PA | NP |
|---|---|---|
| collocation rows (cap 200) | 200 vs 200 | 200 vs 200 |
| collocation Σ O delta | −838 (eng 8,466 / gold 7,628) | −1,069 (eng 8,697 / gold 7,628) |
| n-gram Σ freq delta | −125 | −128 |
| CQL single-term "في" within sentence | 3,309 vs 3,309 (Δ 0) | 3,309 vs 3,309 (Δ 0) |
| CQL two-token, boundary-crossing bigrams | engine finds 2/2/1/1 matches gold misses | engine finds 8/7/4/4/3 matches gold misses |
| CQL two-token, top within-sentence bigrams | Δ 0 (e.g. "جنوب" "السودان" 224 = 224) | Δ 0 (same) |
| CAF mean sentence length (corpus-level) | −5.86 | −11.53 |

Reading (replaces the earlier claim): corpus-scale collocational statistics
are NOT robust to the segmentation difference — the engine's merged
sentences inflate the same-sentence co-occurrence mass (Σ O +838/+1,069)
and n-gram totals, and any two-token CQL pattern whose tokens straddle a
gold boundary silently loses matches under the gold segmentation while the
engine keeps them. The direction is systematic: under-segmentation biases
all sentence-scoped statistics upward on the engine side. Single-term
"within sentence" counts are insensitive by construction and must not be
cited as evidence of segmentation-independence. The 20-doc extrinsic view
(run 41173011756) is superseded by the 222-doc numbers above. Test split
NOT run (user decision).

## 2. Calibration of the segmentation evaluator (A5)

`engine/eval/calibration_sentence.py` (bench/extra-1) reproduces Table 4 of
arXiv:2606.08025 (dev) within 0.21 F1: PA punkt 65.18/65.2, pysbd
63.31/63.1, spacy 67.29/67.3; NP punkt 52.32/52.3, pysbd 52.05/52.1, spacy
54.31/54.3. Root cause of the initial PA mismatch (12–13 F1): punkt /
sentencizer ignore bare newlines while the paper's PA protocol counts
paragraph breaks; NP matched with no change. No evaluator or split change
was needed. Raw calib JSONs: `bench-state/artifacts/calib_{PA,NP}.json`.

## 3. Performance row (production Arabic pipeline, snapshot corpus)

All eight freeze-SHA runs of 2026-10-31 (41173011756, 41173022988,
41176056150, 41181061992, 41185282664, 41189716613, 41194918539,
41202610042 — artifacts and manifests under `benchmarks/results/run-<id>/`)
measured the same production path on identical runners (ubuntu-latest,
4 vCPU, Python 3.12.15, CAMeL-Tools 1.6.0) at engine commit ee42bfa:
sizes 20k/100k/250k tokens × 3 timed repetitions on the snapshot corpus.
The segmentation baseline is bit-identical in all eight runs
(`seg_intrinsic_{PA,NP}.json` are sha256-identical across runs):
PA micro 0.7115 / macro 0.6705; NP micro 0.5572 / macro 0.5469.

Analyze-path medians per run (tok/s), with dialect-ID range and cold load:

| run | 20k | 100k | 250k | dialect ID | cold load |
|---|---|---|---|---|---|
| 41173011756 | 2,708.7 | 2,694.8 | 2,696.9 | 96.7k–98.8k | 4.0 s |
| 41173022988 | 3,939.7 | 3,916.1 | 3,918.1 | 123.4k–124.8k | 2.8 s |
| 41176056150 | 2,805.5 | 2,696.1 | 2,704.8 | 97.2k–99.1k | 3.4 s |
| 41181061992 | 5,433.1 | 5,388.3 | 5,328.6 | 165.3k–167.8k | 2.1 s |
| 41185282664 | 2,811.2 | 2,691.9 | 2,745.8 | 97.2k–98.9k | 3.7 s |
| 41189716613 | 2,685.9 | 2,687.3 | 2,698.4 | 96.5k–98.7k | 3.4 s |
| 41194918539 | 3,969.8 | 3,890.6 | 3,932.9 | 122.1k–123.8k | 2.8 s |
| 41202610042 | 2,766.2 | 2,676.3 | 2,658.7 | 96.8k–99.2k | 3.4 s |

Between-runner spread of the analyze-path median is 2,686–5,433 tok/s at
the 20k input (2.0× across identically configured runs): CI runners are
shared infrastructure and stratify into three speed classes (≈2.7k, ≈3.9k,
≈5.4k analyze-path tok/s; the class is constant within a run across
sizes), so the between-runner component dominates the within-run
component. Within-run CV stays below 1.5% at the 100k and 250k inputs in
all eight runs (max 1.46%); the 20k input is noisier (max 2.72%). Cold
engine load is 2.1–4.0 s across runs; dialect-ID medians span
96.5k–167.8k tok/s and follow the same runner classes. Steady-state
morphology throughput stays consistent with CAMeL-Tools cost bounds.
Bootstrap confidence intervals are computed only for additive measures
(per-question error counts and pass rates); throughput is reported
descriptively with medians and CV%, never with resampling CIs. A single
confirmation run at tag v2.0.2 is scheduled to reproduce this row
(bench plan v3, P1).

## 4. Local grounding rows (Ollama, A3 triples)

Each config: full 80-question bank, 3 independent runs on
`bench/freeze-1-local` @ ee42bfa, scored offline against the frozen gold.

| config | runs (pass rate) | mean pass | runs (halluc. rate) | mean halluc. | verdict flips |
|---|---|---|---|---|---|
| qwen2.5:1.5b | 0.1625 / 0.15 / 0.15 | **0.1542** | 0.625 / 0.6875 / 0.675 | **0.6625** | 16/80 (20%) |
| qwen2.5:3b | 0.075 / 0.075 / 0.0625 | **0.0708** | 0.3625 / 0.3875 / 0.425 | **0.3917** | 24/80 (30%) |
| qwen2.5:7b | probe only (5 q) | — | — | — | — |

7b probe scored (2026-11-01, offline against the frozen gold —
`benchmarks/results/run-41206910830/grounding-probe/paper_report_7b_probe.json`
on the data branch): G-001..G-005 → PASS 0, MISSING_NUMBER 2,
HALLUCINATED 2, TRAP_FAILURE 1 (0/5 passable; diagnostic only, not a row).

Verdict distributions (across runs): 1.5b PASS 12–13, MISSING_NUMBER 11–14,
HALLUCINATED 39–44, TRAP_FAILURE 13–14; 3b PASS 5–6, MISSING_NUMBER 31–37,
HALLUCINATED 23–30, TRAP_FAILURE 14.

Per-category grounding (F5; the bank partitions into 62 answerable questions
with numeric/structured gold and 18 trap/no_tool questions — no_tool,
error, zero-match and expected-absent traps, incl. the 4 category-"trap"
ids G-073/G-074/G-079/G-080; per-run values from the archived
paper_report.json of every run):

| config | answerable (n=62) pass per run | mean | trap/no_tool (n=18) pass per run | mean |
|---|---|---|---|---|
| qwen2.5:1.5b | 11, 10, 10 → 0.177 / 0.161 / 0.161 | **0.167** | 2, 2, 2 → 0.111 | **0.111** |
| qwen2.5:3b | 3, 3, 3 → 0.048 | **0.048** | 3, 3, 2 → 0.167/0.167/0.111 | **0.148** |

Reading: on answerable questions the 1.5b model is ~3.4× better than 3b
(0.167 vs 0.048) — 3b's "safer" failure mode (fewer hallucinations) costs it
nearly all its answerable passes. Both models mostly fall for the
no-tool/zero-match traps (TRAP_FAILURE 13–14 of 18 per run); 3b declines
correctly on 2–3 of 18, 1.5b on 2 of 18 — a small honesty edge to 3b that
does not transfer into usable answers. Trap verdict composition: 1.5b
TRAP_FAILURE 13–14 / HALLUCINATED 2–3 / PASS 2; 3b TRAP_FAILURE 14 /
PASS 2–3 / (1 run each) MISSING_NUMBER 1, HALLUCINATED 1.

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
runbook in `engine/eval/README.md` §4 (bench/extra-1). Probe verdicts
(diagnostic only): MISSING_NUMBER×2, HALLUCINATED×2, TRAP_FAILURE×1
(0/5 passable, scored 2026-11-01).

### F7 — Ollama context truncation confound (measured 2026-11-01)

The grounding harness POSTs to `/api/v1/ai/chat`; the engine's assistant
builds the provider prompt as: SYSTEM_PROMPT (~1,029 Qwen2.5 tokens) +
corpus hint + UI context block (~61) + tool schemas rendered into the prompt
by Ollama (**4,095** tokens, the dominant component) + the question (≤36).
**Turn 1 measures ~5,221 tokens**; pass 2 with three 20-row summarized tool
results measures ~7,576. Ollama's default context is **4k tokens for <24 GiB
VRAM** (docs.ollama.com/context-length, updated 2026-10-27) — the CI runner
is CPU-only (`No NVIDIA/AMD GPU detected` in the run logs; client version
0.40.13, installed via unpinned `install.sh`), so the 4k default applied to
**every local grounding run**: turn 1 was head-truncated by ~1,100 tokens
and pass 2 by ~3,500. The probe's G-001 answer ("Let's try calling the
`get_corpus_overview` tool again…") is consistent with the model not seeing
its tool schemas.

Consequence: the 1.5b/3b rows above (and the 7b probe) were **measured under
context truncation** — the reported pass/hallucination rates are a confound
of model capability AND truncated tool visibility; they must not be cited as
pure capability numbers. The truncation is deterministic (same prompt, same
default) so the A3 triple statistics (flips, CI bands) remain internally
valid. Re-running under a raised context (OLLAMA_CONTEXT_LENGTH=8192, or the
engine fix below) is a maintainer decision and would supersede these rows.
The truncation check was offline and read-only: frozen-code prompt
reconstruction + the real Qwen2.5 tokenizer; the exact per-run truncation
boundaries (which Ollama drops first) are UNVERIFIED — the CI `/tmp/ollama.log`
server logs were not archived.

Post-freeze fix proposed (joins the approval list in §7 finding 4):
`OllamaProvider` should set `options.num_ctx` (env-driven, e.g.
`CORPUSMIND_OLLAMA_NUM_CTX`, unset = Ollama default) so the grounding rows
do not depend on the server's VRAM-bucketed default.

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
- Per-category view of the banked 5 (F5): answerable G-002 **PASS**
  (archived verdict, run 41120607735) and G-040 **PASS** (recorded in the
  plan §7 probe note); G-001 clean answer banked but its verdict is NOT in
  any archived report (UNVERIFIED — recoverable from the probe reports).
  Trap/no_tool: G-073 **PASS** (declined correctly, plan §7 record), G-004
  **FAIL** (answered a no-tool trap with numbers).
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

## 6. Stats-parity check (A6, hardened by F3)

`engine/eval/parity_stats.py` (bench/extra-1, F3 commit 76454a0) compares the
engine's measures with scipy / statsmodels / lexicalrichness with ONE shared
tokenizer handed to both sides, on TWO corpus sets: the 9 snapshot texts
(29–369 tokens) plus F3 deterministic synthetic texts of 10k / 50k / 100k
tokens (Zipf-like, PCG64 seed 20261031) that make the window/segment
measures genuinely comparable. F3 semantics: an empty comparison is reported
as **NOT_TESTED** (null maxima) — never as zero deviation.

| measure | engine vs reference | max abs dev | max rel dev | comparable rows |
|---|---|---|---|---|
| TTR | lexicalrichness | 0 | 0 | all |
| MATTR(50) | lexicalrichness | 1.39e-13 | 2.27e-13 | all (incl. synth) |
| STTR(1000) | lexicalrichness | 8.9e-4 | 0.26% | snapshot-only: **NOT_TESTED**; with synth: 3 |
| HD-D(42) | lexicalrichness | 9.5e-14 | 1.5e-13 | all but 2 excluded |
| Guiraud RTTR | lexicalrichness | 0 | 0 | all |
| Pearson χ² (no Yates) | scipy | 7.1e-15 | 2.4e-16 | 795 of 876 battery tables |
| Dunning G² | scipy | 0 | 0 | 795 of 876 battery tables |
| Odds ratio (uncorrected) | statsmodels `shift_zeros=False` | 0 | 0 | 651 of 876 battery tables |
| MTLD(0.72) | lexicalrichness | 1.3777 | 2.87% | all — convention, disclosed |

F3 battery: 876 deterministic 2×2 tables (the {0,1,2,3,5}⁴ grid — small and
zero cells in every position — + the corpus-derived table + 250 seeded
random tables up to cell 5,000), 373 of them containing at least one zero
cell (max deviation on the comparable zero-cell subset: 0.0 for all three
statistics). Excluded tables are counted and never folded into deviations:
81 (zero margins — scipy raises; engine's raw-χ² convention returns a
number there but there is no reference value) and 225 (raw odds ratio
UNDEFINED, b=0 or c=0).

Corrections this hardening surfaced (F3):
1. The earlier STTR row ("max dev 0 / 0") was the n_comparable=0 case F3
   outlaws: no snapshot text reaches the 1,000-token chunk, so LR excludes
   everything and the old script printed 0/0. It is NOT TESTED on the
   snapshot set. With the 10k–100k texts the real residual appears: LR's
   `msttr(discard=True)` deletes the LAST segment unconditionally — when n
   is an exact multiple of the window that drops one full segment (LR
   source: `del scores[-1]`) — while the engine drops only a trailing
   partial chunk. Convention difference (≤ ~1/segment_count), not an engine
   bug.
2. The statsmodels reference for the odds ratio was `Table2x2(table)` whose
   DEFAULT `shift_zeros=True` silently applies the Haldane 0.5 correction —
   i.e. it matches the engine's separate `odds_ratio_haldane`, not the
   sample `odds_ratio` it was compared against (verified in statsmodels
   source: stored table [[0.5,1],[1,2]] for input [[0,1],[1,2]]). The
   battery now uses `shift_zeros=False`; with that, engine vs statsmodels
   agree exactly on all 651 defined tables.

MTLD remains the only lexical gap and it is a disclosed AGGREGATION
CONVENTION, not a bug: engine = len(tokens)/mean(forward, backward factor
counts); LR = mean of the two directional MTLD scores (the McCarthy &
Jarvis 2010 published form); equal iff both passes find the same factor
count. Raw report: `bench-state/artifacts/a6_parity.json` (regenerated with
the battery this session).

## 7. Scale benchmark (A7) — ingest / KWIC / keyness at 1M and 10M tokens

`scripts/benchmark_scale.py` on `bench/scale-1` (@ 9dd65d2, engine-diff rule
empty), run 41203959363, one matrix leg per size on a fresh SQLite file,
CI runner (ubuntu-latest), full spaCy `en_core_web_sm` 3.8.0 pipeline
(degraded=false — tagger/lemmatizer/parser active), 350-min job cap.
Corpus: SYNTHETIC — **REPETITIVE SYNTHETIC TEXT** (required label): cycled
frozen en-snapshot sentences (~234 types, ~1,000 tok/doc), stated by design.
The A7 primary table below was measured on REPETITIVE SYNTHETIC TEXT; the
F4 re-run table that follows it was measured on the zipf corpus. The
F4 re-run mode (`--corpus-mode zipf`: deterministic PCG64 seed 20261031,
zipf(a=1.15) over a 220,000-type vocabulary, ~20-token sentences) was
subsequently DISPATCHED AND MEASURED on the same branch (commit 9125bbb,
run **41226973126**, workflow_dispatch `grounding_only=SCALE
scale_corpus_mode=zipf`, both matrix legs SUCCESS, 2026-10-31): local 100k
validation had passed (27,322 input types, full pipeline degraded=false,
keyness 100+100 keywords).

A7 primary table — REPETITIVE SYNTHETIC TEXT (run 41203959363):

| phase | 1,000,050 tokens | 10,000,547 tokens | scaling |
|---|---|---|---|
| ingest wall | 348.6 s (3,013 tok/s) | 4,721.3 s (2,129 tok/s) | ~30% throughput drop, sublinear |
| KWIC "the" @limit 400 | 5.87 s (75,632 hits) | 70.25 s (756,340 hits) | ~12× for 10× tokens+index |
| KWIC "goal" @limit 400 | 5.59 s (16,806 hits) | 62.32 s (168,078 hits) | ~11× |
| KWIC ceiling probe "the" @1000 | 14.21 s | 166.6 s | OK at both scales (borderline) |
| keyness (vs 50k reference) | 0.69 s | 8.22 s | linear |
| DB size | 470 MB | 4.52 GB | linear |
| peak RSS (process max) | 238 MiB | 287 MiB | **flat** |

F4 re-run — ZIPF-LIKE 200k+ TYPE TEXT (run 41226973126; realized unique
input types 140,543 @1M and 219,934 @10M — the 220,000-type vocabulary is
essentially fully realized at 10M; queries zw1/zw2 are in-corpus zipf
words):

| phase | 1,000,000 tokens | 10,000,000 tokens | scaling |
|---|---|---|---|
| input types | 140,543 | 219,934 | vocabulary saturates at 10M |
| ingest wall | 439.5 s (2,389 tok/s) | 4,364.3 s (2,303 tok/s) | throughput ~flat (degraded=false) |
| KWIC zw1 @limit 400 | 3.35 s (138,190 hits) | 53.06 s (1,377,841 hits) | ~16× for 10× tokens+hits |
| KWIC zw2 @limit 400 | 4.99 s (61,759 hits) | 44.86 s (621,088 hits) | ~9× |
| KWIC ceiling probe zw1 @1000 | 7.83 s OK | 78.37 s OK | OK at both zipf scales |
| keyness (vs 50k zipf reference) | 0.98 s (+100/−100) | 11.91 s (+100/−100) | linear, full ±100 budget |
| peak RSS (process max) | 293 MiB | 666 MiB | tracks TYPE INVENTORY, not tokens |

Findings:
1. The storage paths scale to 10M tokens on a standard runner — no OOM
   risk. Refined by the F4 zipf re-run (no longer pending): peak RSS is
   flat in CORPUS SIZE at fixed vocabulary (238→287 MiB repetitive;
   293→666 MiB zipf), i.e. memory tracks the type/lemma inventory
   (234 → ~220k types), not token count. Ingest throughput at 10M is
   2,129 tok/s (repetitive) vs 2,303 tok/s (zipf) — the ~30% 1M→10M drop
   seen on repetitive text does not recur on the zipf corpus. Keyness
   reaches its full ±100 keyword budget on zipf text (repetitive 1M could
   only surface +29/−100 — a small-vocabulary artifact, now labeled as
   such).
2. ENGINE SCALE CEILING (reported, not patched — engine frozen for the
   rows; see the approval-request list below): the word-level KWIC context
   fetch builds ONE un-chunked `or_()` over every matched sentence;
   SQLite's expression-depth limit (1000) is crossed when a limit-1000
   query matches ≳950 distinct sentences. The phrase path already chunks
   at 400; the word-level path should chunk the same way. All envelope
   measurements (limit=400) are unaffected; the @1000 probes passed at
   all four measured scales (repetitive 1M/10M, zipf 1M/10M) — the
   ceiling is reached by DISTINCT MATCHES, not corpus size.
3. Failure evidence (F4): the ceiling failure is DETERMINISTIC, not
   intermittent. CI evidence: run **41202901041** (bench/scale-1,
   workflow_dispatch @ c02b3c7, 12:50:46Z), job "Scale (1000000 tokens)"
   FAILED at 12:58:17Z with `sqlite3.OperationalError: Expression tree is
   too large (maximum depth 1000)` (sqlalchemy.exc.OperationalError wrap;
   the 10M leg of that run was cancelled as a consequence). Local
   reproduction: 2026-10-31, 6,000-token corpus (1,200 distinct
   one-"the" sentences) through the production `search_concordance`:
   limit=400 returns OK (400 lines), limit=1000 raises the same error
   (portable repro committed: `scripts/kwic_repro.py` on bench/scale-1
   @ 9125bbb).
4. Post-freeze engine fixes — PROPOSED, NOT MADE (user approval
   required before any implementation; the engine is frozen at ee42bfa and
   every bench branch keeps `git diff ee42bfa -- engine ':!engine/eval'`
   empty):
   - MTLD aggregation: `engine/stats/measures.py` `mtld()` returns
     `len / mean(forward_factors, backward_factors)`; the McCarthy &
     Jarvis (2010) published form — and lexicalrichness — use
     `mean(len/f_forward, len/f_backward)`. Equal only when the two
     directional factor counts coincide; currently disclosed as a
     convention difference in the parity battery. Fix ≈3 lines + tests;
     no frozen gold value quotes MTLD, but it is a visible numeric change
     (semver-minor + battery re-run per house discipline).
   - Word-level KWIC `or_()` chunking: `engine/stats/service.py`
     word-level context fetch (~lines 498–516) should copy the phrase
     path's CHUNK=400 batching (~lines 426–440), removing the
     deterministic depth-1000 ceiling of finding 2/3. Pure query-batching
     change, no result semantics change; gold unaffected; still a
     post-freeze engine edit (new freeze ref required).
   - Ollama `num_ctx` (F7, added 2026-11-01): `OllamaProvider`'s chat
     options set temperature/num_predict/keep_alive but not `num_ctx`, so
     grounding prompts ride the server's VRAM-bucketed default (4k on the
     CPU-only CI runner) and the ~5.2k-token turn-1 prompt is
     head-truncated (§4 F7). Fix: env-driven `options.num_ctx`
     (e.g. `CORPUSMIND_OLLAMA_NUM_CTX`); no result-semantics change, but
     the local rows measured before it carry the truncation confound and
     would need a re-run to supersede.

## 8. Provenance, anomalies, and disclosures

- F7 (2026-11-01, release-eve check): Ollama default-context truncation of
  the local grounding rows — measurement, runner evidence (0.40.13,
  CPU-only) and the third post-freeze fix proposal are in §4. The scored
  7b probe report was committed to the data branch
  (`benchmarks/results/run-41206910830/grounding-probe/
  paper_report_7b_probe.json`).
- Freeze/gold: gold-diff gate GREEN at ee42bfa (runs 41163039515 and
  41173011756, clean=true, diffs=[]). Snapshot branches pushed for every
  completed run; the workflow's automatic snapshot-PR step silently failed
  (known anomaly), so manual data-only PRs were opened: #50 (seg canonical),
  #51 (A4 222-doc), #52–#56 (local rows), #58 (3b #3 snapshot, 41202610042).
  F-order tooling/data PRs: #59 (raw local-run envelopes), #60 (F2+F3 eval),
  #61 (F4 zipf + repetitive labeling). Merge is the maintainer's call;
  nothing has been merged by the bot.
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
- F-order fixes (2026-10-31 follow-up session): F2 pooled extrinsic re-run +
  F3 parity hardening on bench/extra-1 (commit 76454a0; engine-diff rule
  still empty); F4 zipf corpus mode on bench/scale-1 (commit 3ffedaf; gate
  empty); F5 corrections in this report + the plan §1 wording. The F2 run
  used byte-identical AraSEG dev data (parquet sha256 bce3bed0…/3809f267…
  equal to the frozen runs' `araseg_sha256.txt`). Raw outputs:
  `bench-state/artifacts/f2_pooled_{PA,NP}.json`, regenerated
  `bench-state/artifacts/a6_parity.json`, per-category aggregation
  `bench-state/artifacts/f5_per_category.json`. F4 zipf re-run measured on
  2026-10-31 (run 41226973126, both legs SUCCESS; §7 table); raw artifacts
  archived at `bench-state/artifacts/f4-scale-zipf/{1m,10m}/`.
- Archival gap (disclosed): `paper_run.json` for 3b runs #2 (41194918539)
  and #3 (41202610042) is not in any archived artifact (their snapshot
  branches race-predated the grounding artifact; only `paper_report.json`
  was copied to bench-state). Both runs' summary numbers are verified from
  the archived reports and run_meta; the raw run envelopes can be
  re-fetched from Actions artifacts while they remain in retention.

## 9. Measured-at SHAs (v2.0.2 release, added 2026-11-01)

Per-row provenance: which commit produced each measured row above.

| row (section) | measured at | run / evidence |
|---|---|---|
| Segmentation intrinsic + extrinsic, 222 docs (§1) | `ee42bfa` on `bench/freeze-1-seg` | run 41181061992 (A4); canonical 20-doc view 41173011756 (superseded) |
| Segmentation pooled extrinsic, F2 (§1) | `bench/extra-1` @ `76454a0` | local pooled re-run, AraSEG parquets byte-identical (sha256-verified) |
| Evaluator calibration, A5 (§2) | `bench/extra-1` @ `b592cdc` | local calibration_sentence.py; raw calib JSONs on `bench/state` |
| Performance row (§3) | `ee42bfa` | perf job of run 41181061992 (median of 3 reps) |
| qwen2.5:1.5b ×3 (§4) | `ee42bfa` on `bench/freeze-1-local` | runs 41173022988 / 41185282664 / 41189716613 |
| qwen2.5:3b ×3 (§4) | `ee42bfa` on `bench/freeze-1-local` | runs 41176056150 / 41194918539 / 41202610042 |
| qwen2.5:7b probe (§4) | `ee42bfa` on `bench/freeze-1-local` | run 41206910830; scored report on `bench/local-results` @ `c33ac35` |
| Gemini free-tier row (§5) | `ee42bfa` on `bench/freeze-1` (+ probe @ `9c272b8`) | slice run 41181861553; probe 41051082943 (reuse disclosed) |
| Stats parity battery, A6 + F3 (§6) | `bench/extra-1` @ `62af13c` → hardened `76454a0` | `a6_parity.json` on `bench/state` |
| Scale 1M/10M, A7 (§7) | `bench/scale-1` @ `9dd65d2` | run 41203959363 (repetitive corpus, labeled) |
| Scale zipf re-run, F4 (§7) | `bench/scale-1` @ `9125bbb` | run 41226973126 (both legs SUCCESS) |
| KWIC depth-1000 failure evidence (§7) | `bench/scale-1` @ `c02b3c7` | run 41202901041 (job "Scale (1000000 tokens)" FAILED); local repro `scripts/kwic_repro.py` @ `9125bbb` |
| F7 truncation measurement (§4) | offline, engine code @ `ee42bfa` | 2026-11-01; real Qwen2.5 tokenizer + frozen prompt construction; per-run boundaries UNVERIFIED |

**v2.0.2 release statement (MODE A).** Tag `v2.0.2` =
`5a5e43fa0c9e6a903dc06f79579b732a9f666bca`. Engine code in v2.0.2 differs
from the frozen benchmark commit `ee42bfa` ONLY by version constants
(`engine/app/__init__.py` `__version__`, `engine/pyproject.toml` `version`)
— verified by `git diff ee42bfa -- engine ':!engine/eval'` at the tag, plus
the eval-module typing cleanup of #63 (which touches `engine/eval` only and
changes no measured value). Every number in this report was therefore
measured by the code v2.0.2 ships, except where a row names a bench-branch
commit (`76454a0`, `9125bbb`, `b592cdc`, `62af13c`) — those are
`engine/eval`/`scripts` additions that do not alter engine semantics, and
each keeps the freeze gate empty.
