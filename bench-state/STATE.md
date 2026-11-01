# CorpusMind BENCHMARKING — frozen-row state

Read this file FIRST every session and every scheduled turn. Do not act before
checking §7 (next action) and §8 (binding rules). Never put secrets in this file.

Last updated: 2026-10-31T15:05Z (T6 COMPLETE: PR #57 open — BENCHMARK_REPORT.md + free-tier fix; secret CORPUSMIND_CLOUD_API_KEY deleted from the repo; scheduled jobs 489478/489479 DELETED; A1-A9 all DONE; Gemini row left IN PROGRESS at 5/80 as a disclosed limitation; user must revoke the leaked GitHub token)

## 1. Freeze

- Freeze SHA: `ee42bfab72291072b191ebb4c7d77ec03bb1f94d` (= main @ ee42bfa,
  "docs(bench): reframe the Gemini reference row as free-tier-by-design (#49)")
- Branches, all at the freeze SHA: `bench/freeze-1` (Gemini crawl),
  `bench/freeze-1-local` (local rows), `bench/freeze-1-seg` (segmentation)
- sha256 `engine/eval/questions.py` =
  `b521cbb1f8e2be3a0316d0042ccd8937bcc3d4173cafeb43b82da4ce41d989c7`
- sha256 `engine/eval/data/gold/grounding_gold.json` =
  `480f5230955ae32e52d52bce51e82a0244ea44f9ae110c37dcf3afc16e6dac13`
- Bank size: 80 questions, ids G-001..G-080
- Gold-diff gate: GREEN — run 41163039515, job "Gold diff (rebuild all vs
  frozen)" = success @ 4d44a1c (content-identical to ee42bfa for
  engine/shared/reference-data; diff 0 lines). In-freeze confirmation:
  run 41173011756 on bench/freeze-1-seg with run_gold_diff=true (result: see §9).

## 2. Crawl parameters (frozen for the Gemini row)

`grounding_provider=cloud cloud_vendor=gemini grounding_model=gemini-3.8-flash
reasoning_effort=low grounding_pause=2 grounding_timeout=600
grounding_chat_deadline_s=600 debug_raw=false commit_results=false`
Dispatch on `bench/freeze-1` via `bench-state/scripts/dispatch_crawl.sh <ids...>`.
Free tier = 20 requests/day per project, resets midnight Pacific.
Daily budget: morning slice ≤16 ids, drip slice ≤4 ids (retry or advance).

## 3. Banked-question table (Gemini row)

| id    | status  | earliest clean run | run SHA  | `git diff <SHA>..freeze -- engine shared reference-data` | usable for freeze row |
|-------|---------|--------------------|----------|----------------------------------------------|-----------------------|
| G-001 | BANKED  | 41055467044        | 0704955  | 0 lines                                      | YES                   |
| G-002 | BANKED  | 41120607735        | bd25058  | 0 lines                                      | YES                   |
| G-004 | BANKED (A2) | 41051082943 (11:51Z) | 9c272b8 | 0 lines excluding engine/tests | YES — reused, disclosed |
| G-040 | BANKED (A2) | 41051082943 (11:51Z) | 9c272b8 | 0 lines excluding engine/tests | YES — reused, disclosed |
| G-073 | BANKED (A2) | 41051082943 (11:51Z) | 9c272b8 | 0 lines excluding engine/tests | YES — reused, disclosed |

- A2 (addendum 2026-10-31): the reuse rule now EXCLUDES engine/tests.
  `git diff 9c272b8..ee42bfa -- engine shared reference-data ':!engine/tests'`
  = 0 lines, so G-004, G-040, G-073 are BANKED from probe run 41051082943
  (earliest REUSABLE clean; 41026068623 @ afce8fe is earlier at 08:23Z but its
  diff is 1692 lines even excluding tests -> not reusable). REUSE DISCLOSED.
  Caveat carried into the report: these probe answers scored under the
  PRE-freeze gold (#43/#44 re-froze it) and G-004 was an honest-trap fail;
  the freeze-row score for G-004 will reflect that (reported as-is).
- Off-spec probe attempts, Oct-30 evening, ZERO clean answers (disclose in
  report; consumed Oct-30 quota tail): 41125306050 (gemini-3.8-flash-lite,
  G-005 failed), 41127495897 (gemini-3.8-pro, G-006 failed), 41129889514
  (gemini-3.8-flash, G-001..G-008 all failed), 41134947351 (gemini-3.8-flash,
  G-003 failed). All errors: "Model call failed: [cloud] chat request failed".
- Duplicate asks to disclose at merge time: G-004 asked 2× clean (08:23Z, 11:51Z
  Oct-30), G-040 2× clean (same), G-073 1 dirty + 1 clean. None are on the
  freeze row; the freeze-row answer will be the earliest FREEZE-clean one.
- Local row (superseded): run 41028985957 @ afce8fe, qwen2.5:1.5b (ollama),
  80/80 clean answers — diff afce8fe..freeze = 1936 lines → superseded by the
  re-run in §9.

## 4. Slice log

| date (Pacific) | slice | run id | ref | ids | clean | dirty-infra | notes |
|---|---|---|---|---|---|---|---|
| 2026-10-30 | probe   | 41051082943 | main@9c272b8 | G-040,G-073,G-004 | 3 | 0 | pre-freeze, diff 94 |
| 2026-10-30 | attempt | 41055467044 | main@0704955 | 80 (G-001 clean, 79×429) | 1 | 79 | quota tail |
| 2026-10-30 | attempt | 41120607735 | main@bd25058 | G-002 | 1 | 0 | banked |
| 2026-10-30 | attempt | 41125306050 | main@bd25058 | G-005 | 0 | 1 | OFF-SPEC model flash-lite |
| 2026-10-30 | attempt | 41127495897 | main@bd25058 | G-006 | 0 | 1 | OFF-SPEC model pro |
| 2026-10-30 | attempt | 41129889514 | main@bd25058 | G-001..G-008 | 0 | 7 | quota exhausted |
| 2026-10-30 | attempt | 41134947351 | main@bd25058 | G-003 | 0 | 1 | quota exhausted |
| 2026-10-31 | slice-1 | 41181861553 | bench/freeze-1 @ ee42bfa | G-003,G-005..G-019 (16) | 0 | 16 | completed 09:17Z; 15× 'Model call failed: [cloud] chat request failed: H…' (429-class) + G-003 600s deadline exceed; raw artifact in bench-state/artifacts/2026-10-31-run-41181861553/. ZERO-CLEAN DAY 1 of the 3-day stop rule. All 16 ids remain UNBANKED; the 15:30 drip may retry ≤4 (infra failures only) |

## 5. Crawl queue (unbanked order for bench/freeze-1)

Banked-for-freeze: G-001, G-002, G-004, G-040, G-073 (5/80). 75 unbanked.

1. slice-1 (≤16): G-003 G-005 G-006 G-007 G-008 G-009 G-010 G-011 G-012 G-013 G-014 G-015 G-016 G-017 G-018 G-019
2. drip (≤4): retry infra-dirty of slice-1 (max 4); if none, advance: G-020 G-021 G-022 G-023
3. then in order: G-024 … G-039, G-041 … G-072, G-074 … G-080 (55 remaining after today)

Slice sizing rule: never exceed 20 dispatched questions per Pacific day across
both slices (16 morning + 4 drip). If the observed quota is tighter (see §10),
shrink to what succeeds and update this file.

## 6. Schedule

- DELETED 2026-10-31 ~15:00Z at T6 (per the addendum cleanup step):
  `corpusmind-gemini-daily` (489478) and `corpusmind-gemini-drip` (489479).
  Zero scheduled jobs remain (verified by scheduler list). Their payloads
  embedded the GitHub token, so deletion also removes that exposure from
  the scheduler. The Gemini row stays IN PROGRESS at 5/80 banked; resuming
  later = recreate the two jobs (or dispatch manually) with the §2 params
  and a fresh token.
- (old IDs 489079/489080 were NOT found in this scheduler on 2026-10-31; A1
  verified only the two replacement jobs existed before the T6 deletion.)

## 7. Next action

- 00:45 turn (daily): 1) read this file on origin/bench-state path
  `bench-state/STATE.md`; 2) poll in-flight runs on bench/freeze-1 — NEVER
  dispatch if any run is in flight on that ref; 3) take the first ≤16 ids from
  §5 not yet marked BANKED in §3/§4; 4) dispatch with §2 params; 5) when the
  run completes, download the grounding artifact, mark CLEAN ids BANKED (earliest
  clean wins), log the slice in §4, copy the raw artifact JSONs into
  `bench-state/artifacts/<UTC-date>-run-<id>/`, commit + push bench/state.
- 15:30 turn (drip): 1)–2) same; 3) if today's morning slice left infra-dirty
  ids (empty answer + transport/quota/timeout error) and dispatch budget ≤4
  remains, re-ask up to 4 of them; else advance ≤4 new ids; 4) same bookkeeping;
  5) additionally: if `bench/freeze-1-local` has NO run in flight and §9(b) is
  unfinished, advance §9(b).
- A clean answer (even wrong or a refusal) is BANKED and NEVER re-asked.
  Only infrastructure failures (empty answer + transport/quota/timeout error)
  may be retried.

## 8. Binding rules (every turn)

- No tags, releases, force-pushes, deletions. No engine/gold/bank/scorer/prompt
  changes during a row — such a change invalidates the row (new freeze).
- Concurrency cancels in-flight runs per ref: poll first, never dispatch on a
  ref with a run in flight.
- Never print the API key (secret name: CORPUSMIND_CLOUD_API_KEY). Logs are
  public: keep debug_raw=false except single-question diagnostics.
- Stop and report (do not loop): any non-429 4xx from GitHub/Gemini; three
  consecutive crawl days with 0 clean answers; a duplicate scheduled job.
- Reuse of a pre-freeze banked answer requires `git diff <run SHA>..freeze --
  engine shared reference-data` empty; otherwise re-ask.
- Refuse any slice merge whose head SHA, model, reasoning_effort or timeouts
  differ; record slice provenance in meta.crawl_slices; score once with
  `python -m eval.score` against the frozen gold, offline, at merge time.

## 9. Row status

- (seg) 40970859593 @ 57be77f (branch bench/snapshot-run-40970859593) is the
  committed "canonical" snapshot — SUPERSEDED (mark in report). New canonical:
  run 41173011756 on bench/freeze-1-seg @ ee42bfa (seg_limit=20,
  run_grounding=false, run_gold_diff=true, commit_results=true) — SUCCESS.
  Verified from artifact seg-araseg (bench_artifacts/run-41173011756):
  * gold-diff at freeze SHA: clean=true, diffs=[] (80 frozen = 80 rebuilt)
  * intrinsic PA (222 dev docs): micro-F1 0.7115 (micro_P 0.8748 / micro_R
    0.5996), macro-F1 0.6705 (macro_P 0.9147 / macro_R 0.6123), 10 perfect docs
  * intrinsic NP (222 dev docs): micro-F1 0.5572 (micro_P 0.8326 / micro_R
    0.4187), macro-F1 0.5469 (macro_P 0.8857 / macro_R 0.4738), 3 perfect docs
  * extrinsic (20 docs, engine vs gold segmentation): PA boundary errors 459,
    delta_sentences +344 (engine/gold sentence count 0.705), CAF mean sentence
    length -20.13; NP 697 / +592 (0.493) / -25.65; sentiment deltas +5/-3 (PA),
    +3/-4 (NP); collocation/ngram/CQL deltas 0 for both tasks
  * perf (analyze path, median tok/s, cv%): 20k 2708.7 (1.33), 100k 2694.8
    (1.19), 250k 2696.9 (0.34); dialect-id ~96.6k-98.8k tok/s; cold load 4.0 s
  * snapshot branch bench/snapshot-run-41173011756 pushed (data-only); the
    bot's PR step silently failed — open the PR manually at merge time
  * test split NOT run (per user decision)
- (local-a) DONE. Run 41173022988 on bench/freeze-1-local @ ee42bfa
  (qwen2.5:1.5b, ollama, full 80, commit_results=true), SUCCESS 06:04Z, 80/80
  clean answers. Scored vs frozen gold (artifact grounding-report):
  pass_rate 0.1625 (CI95 0.0875-0.2375), hallucination_rate 0.625 (CI95
  0.525-0.725); verdicts PASS 13 / MISSING_NUMBER 14 / HALLUCINATED 39 /
  TRAP_FAILURE 14. The afce8fe row (41028985957; pass 0.1375, halluc 0.65 per
  brief — not re-verified this session) is SUPERSEDED; note the delta reflects
  engine+gold changes (#43/#44), not engine effect alone. Snapshot branch
  bench/snapshot-run-41173022988 patched with grounding/ (data-only commit) —
  the results-snapshot job had raced ahead of the grounding artifact. On success, mark 41028985957
  superseded. Prior row (to be replaced): pass 0.1375, hallucination 0.65
  (UNVERIFIED here; verify by re-scoring the new run).
- (local-b) qwen2.5:3b — timing probe DONE: run 41175198604 (5 questions
  G-001..G-005, commit_results=false), SUCCESS 06:17Z. Grounding job 11.4 min,
  mean 95.8 s/q (max 125.5) → full-80 projection 127.7 min (job-level 182 min)
  ≤ 330 min → FITS. FULL RUN DISPATCHED: 41176056150 on bench/freeze-1-local
  @ ee42bfa (full 80, commit_results=true), IN FLIGHT since 06:18:28Z, ETA ~3 h.
  On completion: download grounding-report, score, record numbers, patch the
  snapshot branch with grounding/ if missing (same race as local-a).
  NEXT after that: qwen2.5:7b timing probe the same way (5 questions,
  grounding_only="G-001 G-002 G-003 G-004 G-005", commit_results=false) on an
  idle freeze-1-local; full bank only if projection ≤ 330 min. If 7b does not
  fit: write a one-command runbook in engine/eval/README.md (on a bench branch,
  NOT a freeze ref) and mark the 7b row "pending user-run".
- (gemini) IN PROGRESS: banked 5/80 reusable (A2 added G-004/G-040/G-073 from
  the probe run). ~4-5 Pacific days at 16+4/day if clean; re-check §5 every turn.
  A8: the crawl is OPTIONAL for T6 — T6 records only completed rows and must
  not wait; if incomplete at T6, write it into the limitations and cite the
  probe runs (41051082943, 41055467044) as incident evidence only.

- (A3 local rows, addendum) Each config runs 3× on bench/freeze-1-local (full
  80, commit_results=true). Report all runs, the mean pass/hallucination, and
  the number of questions whose verdict flips across the runs. Chain order
  (serialized, poll before each dispatch):
    1. 3b #1 — 41176056150 DONE 08:3xZ, 80/80 clean, pass 0.075
       [0.025-0.1375], halluc 0.3625 [0.2625-0.475]; verdicts PASS 6 /
       MISSING_NUMBER 37 / HALLUCINATED 23 / TRAP_FAILURE 14. Snapshot branch
       bench/snapshot-run-41176056150 patched with grounding/.
    2. 1.5b #2 — 41185282664 DONE 09:41Z, 80/80 clean, pass 0.15
       [0.075-0.2375], halluc 0.6875 [0.5875-0.7875]; verdicts PASS 12 /
       MISSING_NUMBER 11 / HALLUCINATED 44 / TRAP_FAILURE 13. Snapshot
       bench/snapshot-run-41185282664 patched with grounding/.
    3. 1.5b #3 — 41189716613 DONE 10:58Z, 80/80 clean, pass 0.15
       [0.075-0.225], halluc 0.675 [0.575-0.775]; verdicts PASS 12 /
       MISSING_NUMBER 12 / HALLUCINATED 43 / TRAP_FAILURE 13. Snapshot
       bench/snapshot-run-41189716613 patched with grounding/.
       1.5b TRIPLE COMPLETE: pass 0.1625 / 0.15 / 0.15 (mean 0.1542);
       halluc 0.625 / 0.6875 / 0.675 (mean 0.6625). Verdict-flip analysis at
       T6 from the three paper_report.json artifacts (on snapshot branches).
    4. 3b #2 — 41194918539 DONE 12:27Z (scored), 80/80 clean, pass 0.075
       [0.025-0.1375], halluc 0.3875 [0.2875-0.4875]; verdicts PASS 6 /
       MISSING_NUMBER 36 / HALLUCINATED 24 / TRAP_FAILURE 14. run_meta
       confirms ollama/qwen2.5:3b. paper_report.json archived under
       bench-state/artifacts/run-41194918539/.
    5. 3b #3 — 41202610042 DONE 13:41Z, 80/80 clean, pass 0.0625
       [0.0125-0.1125], halluc 0.425 [0.3125-0.5375]; verdicts PASS 5 /
       MISSING_NUMBER 31 / HALLUCINATED 30 / TRAP_FAILURE 14. run_meta
       confirms ollama/qwen2.5:3b.
       3b TRIPLE COMPLETE: pass 0.075/0.075/0.0625 (mean 0.0708); halluc
       0.3625/0.3875/0.425 (mean 0.3917). VERDICT FLIPS 24/80 (30%):
       18× HALLUCINATED<->MISSING_NUMBER, 4× involve PASS, 2× involve
       TRAP_FAILURE (detail: bench-state/artifacts/a3_verdict_flips_3b.json).
       READING: 3b fails 'safer' than 1.5b (shifts HALLUCINATED ->
       MISSING_NUMBER: mean hallucination 0.39 vs 0.66) but passes less
       (mean 0.0708 vs 0.1542); both local rows are far below any usable
       operating point and flips show single-question instability, not
       systematic verdict migration.
    6. 7b probe — 41206910830 DONE 14:11Z. 5/5 clean answers (verdicts
       G-001..G-005: MISSING_NUMBER x2, HALLUCINATED x2, TRAP_FAILURE x1 —
       diagnostic only, not a row; paper_run.json archived under
       bench-state/artifacts/run-41206910830/). Timing 313.8/241.8/270.1/
       331.5/200.3 s -> mean 271.5 s/q -> full-80 projection 362 min > 330-min
       cap -> DOES NOT FIT. Per the pre-registered rule: one-command runbook
       written into engine/eval/README.md on bench/extra-1 (@ 697458c, never
       a freeze ref); 7b ROW = PENDING USER-RUN.
  1.5b #1 = 41173022988 (done: pass 0.1625 [0.0875-0.2375], halluc 0.625
  [0.525-0.725]). The afce8fe row 0.1375/0.65 stays labelled SUPERSEDED.
  1.5b TRIPLE WRAP (2026-10-31): pass 0.1625/0.15/0.15 (mean 0.1542);
  halluc 0.625/0.6875/0.675 (mean 0.6625); VERDICT FLIPS 16/80 (20%) across
  the three runs — analysis + per-question detail in
  bench-state/artifacts/a3_verdict_flips_1.5b.json. Flip composition:
  11× HALLUCINATED<->MISSING_NUMBER, 1× HALLUCINATED<->TRAP_FAILURE, 4×
  involve PASS (G-034, G-043, G-046, G-071) — single-question passes are
  unstable across runs, no systematic direction.

- (A4) DONE. Run 41181061992 on bench/freeze-1-seg @ ee42bfa (seg_limit=222,
  commit_results=true), SUCCESS 07:45Z. 222 docs per condition; intrinsic
  bit-identical to the frozen row (PA micro 0.7115/macro 0.6705; NP 0.5572/
  0.5469). Extrinsic (gold-minus-engine, 222 docs): PA boundary_errors 6313,
  delta_sentences +5291 (engine/gold sentence count 0.616), CAF
  delta_mean_sentence_length -62.71, sentiment +54/-99, collocation/ngram/
  CQL deltas 0; NP 8641, +7593 (0.449), -88.27, +68/-122, others 0.
  The 20-doc extrinsic view (41173011756) is superseded. Sign
  convention stated in engine/eval/README.md on bench/extra-1: the code
  computes deltas as GOLD MINUS ENGINE (positive = engine produced fewer);
  the addendum's 'engine minus gold' wording corresponds to negating every
  delta. The 20-doc extrinsic view (41173011756) is superseded by the 222-doc
  numbers once this run lands.

- (A5) DONE, gate PASS. engine/eval/calibration_sentence.py on bench/extra-1
  (b592cdc) reproduces Table 4 of arXiv:2606.08025 (dev) within 0.21 F1:
  PA punkt 65.18/65.2, pysbd 63.31/63.1, spacy 67.29/67.3;
  NP punkt 52.32/52.3, pysbd 52.05/52.1, spacy 54.31/54.3.
  Root cause of the initial PA mismatch (12-13 F1): punkt/sentencizer ignore
  bare newlines; the paper's PA protocol counts paragraph breaks. NP matched
  exactly with no change. No evaluator or split change was needed; the
  finding is documented in engine/eval/README.md and the raw calib JSONs are
  on bench/state (bench-state/artifacts/calib_{PA,NP}.json).

- (A6) DONE 2026-10-31 (run executed early, in parallel with the A3 local
  chain — CPU-local work on the bench/extra-1 worktree only, zero contact
  with any frozen row; deviation from the A1..A9 sequencing noted here for
  the record). Script engine/eval/parity_stats.py on bench/extra-1
  (@ 62af13c after two fix commits, engine-diff rule still 0 lines vs
  ee42bfa). Shared-corpus set: the 9 snapshot texts (8 + en_all concat),
  29..369 tokens each, ONE shared regex tokenizer (\w+) handed to both
  sides. Results (max abs / max rel dev across corpora):
    TTR 0 / 0; MATTR(50) 2.0e-15 / 2.4e-15; STTR(1000) 0 / 0;
    HD-D(42) 1.4e-15 / 1.7e-15; Guiraud RTTR 0 / 0;
    chi-square 0 / 0; Dunning G^2 0 / 0; odds-ratio 0 / 0.
    MTLD(0.72): max_abs 1.3777, max_rel 0.0287 (en_learner) — CONVENTION
    DIFFERENCE, checked and disclosed: engine = len/mean(forward,
    backward factor counts); LR = mean of the two directional MTLD scores
    (the McCarthy & Jarvis 2010 published form). Equal iff forward ==
    backward factor counts; not scored as an engine error.
  Fix history (A6 rule "check the other tool's convention" in action):
    1st run had NaN/inf/large gaps -> root causes: (a) LR 0.5.x default
    preprocessing (lowercase, strip punct/digits) broke the shared-token
    premise — fixed by pinning LR with preprocessor=identity and a
    tokenizer closure returning the exact shared token list; (b) engine
    odds_ratio takes (f1, f2, N1, N2), not 2x2 cells — mapped
    (a, c, a+b, c+d); (c) LR 0.5.1 names the HD-D parameter 'draws';
    (d) window measures: corpora shorter than the window are excluded on
    the LR side (LR raises; engine falls back to raw TTR) — disclosed.
  Raw artifact: bench-state/artifacts/a6_parity.json.

- (A7) DONE 2026-10-31. scripts/benchmark_scale.py + a
  gated `scale` job inside .github/workflows/benchmarks.yml on new branch
  bench/scale-1 (@ 9dd65d2, at ee42bfa; engine-diff rule 0 lines). NOTE: a
  new workflow file on a side branch is NOT dispatchable via the API
  (GitHub registers workflows from the default branch only — dispatch of
  scale.yml returned 404), so the job piggybacks on the already-
  dispatchable benchmarks.yml, gated on `inputs.grounding_only == 'SCALE'`
  (schema-compatible with main; run_grounding stays false so no Gemini
  quota is used). Run history: 41202459225 FAILED (SQLite could not create
  the DB file — custom CORPUSMIND_DB_URL parent dir not auto-created;
  fixed by mkdir in the script); retry FAILED at the KWIC phase (engine
  word-level context fetch builds ONE un-chunked or_() over all matched
  sentences — SQLite 'Expression tree is too large (maximum depth 1000)'
  when a limit=1000 query matches ≳950 distinct sentences at 1M tokens;
  the phrase path chunks at 400, the word-level path does not — ENGINE
  SCALE FINDING, reported not patched, engine frozen); final run
  41203959363 @ 9dd65d2 with an envelope design: measure inside the
  envelope (limit=400) + one ceiling probe at limit=1000 + incremental
  per-phase report dumps.
  1M leg RESULTS (run 41203959363, artifact scale-1000000, archived
  bench-state/artifacts/a7-scale/1m/): corpus 994 docs / 1,000,050 tokens
  (cycled frozen en-snapshot sentences, vocab 234 types); INGEST 348.6 s
  = 3,013 tok/s (FULL en_core_web_sm 3.8.0 pipeline, degraded=false);
  KWIC 'the'@400 5.87 s (75,632 total matches), 'goal'@400 5.59 s
  (16,806), ceiling probe 'the'@1000 14.21 s OK (borderline envelope);
  KEYNESS 0.69 s (+29/-100 keywords); DB 470 MB; peak RSS 238 MiB.
  10M leg RESULTS (same run 41203959363, artifact scale-10000000, archived
  bench-state/artifacts/a7-scale/10m/): 9,940 docs / 10,000,547 tokens;
  INGEST 4,721.3 s = 2,129 tok/s (throughput drops ~30% vs 1M — sublinear
  but healthy at a 4.52 GB SQLite file); KWIC 'the'@400 70.25 s (756,340
  matches), 'goal'@400 62.32 s (168,078), ceiling probe @1000 166.6 s OK
  (still under the depth limit — borderline at both scales);
  KEYNESS 8.22 s (+30/-100, same top terms); PEAK RSS 287 MiB — essentially
  FLAT vs 238 MiB at 1M (the pipeline streams; memory does not track
  corpus size). HEADLINE: storage paths scale to 10M tokens on a standard
  runner with no out-of-memory risk; the only ceiling found is the KWIC
  expression-depth limit above.

## 10. Known anomalies / open items for the report

- Oct-30 quota accounting is inconsistent with a plain 20/day pool (79×429 at
  12:27Z, then a clean G-002 at 20:06Z the same Pacific day). Treat slices as
  adaptive: never exceed 20/day, shrink if 429 walls appear early.
- Oct-31 07:45Z (= 00:45 PDT, right after the nominal reset): all 16 slice-1
  attempts failed (15× 429-class, 1× deadline). A fresh 20/day pool would
  have allowed ~16 clean — the reset/quota model in the brief is NOT holding
  (day-2 evidence). The 15:30 drip turn will retry ≤4; if the pattern
  persists, the crawl stalls regardless of budget — surface to the user at
  T6 (A8: crawl optional; probe runs remain incident evidence).
- Two off-spec model attempts happened Oct-30 evening (flash-lite, pro) — see
  §3; zero clean answers, disclosed.
- RESOLVED at T6: docs/BENCHMARK_IMPROVEMENT_PLAN.md section 5 "PAID key"
  wording fixed to FREE-TIER BY DESIGN and docs/BENCHMARK_REPORT.md added —
  both in docs-only PR #57 (bench/t6-report; engine-diff rule 0 lines).
  The repository secret CORPUSMIND_CLOUD_API_KEY was DELETED (API 204,
  remaining secrets list empty). USER ACTION STILL REQUIRED: revoke and
  rotate the GitHub token that was pasted into the original chat (it was
  embedded in the scheduled-task payloads until deletion; the repo secret
  was separate).
- Brief said canonical seg snapshot was @ 06de47b; the actual snapshot run
  40970859593 is @ 57be77f. Superseded either way by §9(seg).
- The workflow's "Open snapshot PR" step silently failed for runs 41173011756
  and 41173022988 (step reports success via `|| echo`; no PR exists). RESOLVED
  2026-10-31 ~13:40Z: manual data-only PRs opened for ALL completed snapshot
  branches — #50 (41173011756 seg canonical), #51 (41181061992 A4 222-doc),
  #52 (41173022988 1.5b#1), #53 (41176056150 3b#1), #54 (41185282664 1.5b#2),
  #55 (41189716613 1.5b#3), #56 (41194918539 3b#2). Merge decision is the
  maintainer's; merging makes the citable snapshots visible on main.
- Oct-30 20:42-21:58Z dispatch runs (4 in §3) were not in the original brief;
  all 0 clean, two off-spec models. No bank impact.

## 11. F-order follow-up session (2026-10-31, after T6) — LOCAL ONLY, pushes blocked

SESSION CONSTRAINT: the sandbox was recycled — the GitHub token is NOT in
the environment any more and the anonymous API is rate-limited, so NOTHING
could be pushed, no PR opened, no workflow dispatched this session. All work
below exists as LOCAL commits on local branches (SHAs listed; push with a
fresh token, fast-forward, no force). No frozen ref was touched; the
engine-diff gate `git diff ee42bfa -- engine ':!engine/eval'` verified empty
for every branch listed. In-flight runs at session start: NONE (all A-runs
finished; scheduled jobs absent, consistent with the T6 deletion).

- (F2) DONE. `engine/eval/segmentation_downstream.py` gained a pooled mode
  (--pool, thresholds --min-colloc-freq/--min-ngram-freq, data-driven
  TWO-TOKEN CQL patterns, word-token filter). TWO BUGS FOUND in the legacy
  recording: (a) it read `top_collocates`/`top_ngrams` while the REST
  endpoints return `rows` — the frozen artifacts' zeros were partly this key
  bug; (b) the single-term CQL pattern cannot show a delta by construction.
  Pooled re-run LOCAL (AraSEG dev parquets sha256-verified byte-identical to
  the frozen runs: bce3bed0…/3809f267…), 222 docs per condition, min_freq 5:
  the pooled corpus reproduces the frozen per-doc totals EXACTLY (boundary
  errors 6,313/8,641; delta sentences +5,291/+7,593; sentiment +54/−99,
  +68/−122) — design validated. New numbers (gold−engine): colloc ΣO
  −838 (PA) / −1,069 (NP); ngram Σfreq −125/−128; single-term CQL 0 (both);
  two-token boundary-crossing bigrams: engine finds matches gold misses
  (PA 2/2/1/1; NP 8/7/4/4/3); top within-sentence bigrams Δ0 (e.g.
  "جنوب السودان" 224=224); CAF corpus-level −5.86/−11.53. "Robust to
  segmentation" DELETED from the report — the data says the opposite.
  Artifacts: bench-state/artifacts/f2_pooled_{PA,NP}.json.
- (F3) DONE. parity_stats.py: compare() now emits status NOT_TESTED with
  null maxima for empty comparisons (STTR n_comparable=0 is NOT_TESTED,
  never 0/0); deterministic synth texts 10k/50k/100k (Zipf-like, PCG64 seed
  20261031); 876-table 2x2 battery ({0,1,2,3,5}^4 grid + corpus table + 250
  seeded random), 373 zero-cell tables, exclusions counted not folded in.
  TWO REFERENCE CORRECTIONS: (a) statsmodels Table2x2 DEFAULT
  shift_zeros=True silently applies the Haldane correction — battery now
  uses shift_zeros=False (sample OR); engine agrees EXACTLY (651 defined
  tables, max dev 0); (b) STTR residual vs LR is LR's unconditional
  last-segment discard (msttr `del scores[-1]`), observed 2.6e-3 rel —
  convention, not a bug. chi² 7.1e-15 max; G² exact 0. Artifact:
  bench-state/artifacts/a6_parity.json (regenerated).
- (F4) PARTIAL (code + evidence done; 1M/10M zipf legs pending dispatch).
  scripts/benchmark_scale.py --corpus-mode zipf (PCG64 20261031, zipf 1.15,
  vocab 220,000, ~20-token sentences; KWIC words zw1/zw2 — numpy zipf draws
  start at 1, zw0 never occurs); repetitive mode self-labels output
  REPETITIVE SYNTHETIC TEXT. Local validation 100k tokens (full pipeline,
  degraded=false): 27,322 input types vs 234 repetitive; ingest 3,260 tok/s;
  keyness 100+100 keywords. The KWIC limit-1000 failure is DETERMINISTIC —
  reproduced locally via production search_concordance, 1,200 distinct
  one-"the" sentences: limit=400 OK (400 lines), limit=1000 raises
  `sqlite3.OperationalError: Expression tree is too large (maximum depth
  1000)` (repro: scripts/kwic_repro.py, session-local). The A7 CI retry run
  that first hit the ceiling was never recorded by run ID in this file (the
  41202459225 and 41203959363 runs bracket it); fetch the ID from Actions
  history when API access returns. PENDING DISPATCH (needs token):
    CORPUSMIND_DB_URL=sqlite+aiosqlite:////tmp/scale/scale.db (set by job)
    dispatch benchmarks.yml on bench/scale-1 @ 3ffedaf with
    grounding_only="SCALE", the job must run:
    python scripts/benchmark_scale.py --sizes 1000000,10000000 --corpus-mode zipf
  (workflow gate inputs.grounding_only == 'SCALE' already wired @ 9dd65d2+).
- (F5) DONE (docs, on bench/t6-report local commit a0b3283): report §1
  pooled-extrinsic correction + "robust" claim deleted; §4 per-category
  grounding (62 answerable vs 18 trap/no_tool: 1.5b mean 0.167 answerable /
  0.111 trap; 3b 0.048 / 0.148); §5 per-category view of the banked 5
  (G-001 verdict UNVERIFIED — clean answer banked, verdict in no archived
  report); §6 parity corrections; §7 REPETITIVE label + zipf + KWIC
  evidence; plan §1 wording fixed to "on par with the best classical
  baseline on PA (67.05 vs spaCy 67.29), above on NP". Aggregation script +
  artifact: f5_per_category.json.
- (F1) STAGED, NOT OPENED (needs token). Local branches ready:
  * bench/local-results @ ce77f49 (NEW, off ee42bfa, data-only): raw
    paper_run/paper_report.json for ALL six local runs (1.5b ×3, 3b ×3) +
    7b probe paper_run.json + README-local-runs.md. Gate: 0 lines.
  * bench/extra-1 @ 76454a0 (1 ahead of origin 697458c): F2+F3.
  * bench/scale-1 @ 3ffedaf (1 ahead of origin 9dd65d2): F4.
  * bench/t6-report @ a0b3283 (1 ahead of origin 9f16790): F5 (updates PR #57).
  PR bodies pre-written: bench-state/pr-bodies-f1.md. PROPOSED MERGE ORDER
  after push: #50→#51 (data snapshots), #52→#56, NEW 3b#3 snapshot PR
  (bench/snapshot-run-41202610042 — PR was never opened for it), NEW
  bench/local-results PR, NEW bench/extra-1 PR, NEW bench/scale-1 PR, then
  #57 (report) LAST so it lands with its artifacts. Nothing merged by the
  bot; maintainer decides.
- (F6) POST-FREEZE ENGINE FIXES — PROPOSED, NOT MADE (user approval required):
  1. MTLD aggregation: engine/stats/measures.py mtld() returns
     len/mean(forward_factors, backward_factors); the McCarthy & Jarvis 2010
     published form (and LR) is mean(len/f_f, len/f_b). Fix = swap the
     aggregation (≈3-line change + tests). Exposure: corpus-stats
     lexical_diversity battery (stats/service.py). NO frozen gold value
     quotes MTLD (0 occurrences in grounding_gold.json) → gold-diff gate
     unaffected, but it is a visible numeric change → semver-minor + battery
     re-run per house discipline.
  2. Word-level KWIC or_() chunking: stats/service.py word-level context
     fetch (~line 498-516) builds ONE un-chunked or_() over all matched
     (doc, sentence) pairs; copy the phrase path's CHUNK=400 batching
     (lines ~426-440). Removes the deterministic SQLite depth-1000 ceiling
     (see F4 repro). Pure query-batching change, no result semantics change;
     gold unaffected; still a post-freeze engine edit (new freeze ref).
- (7b quantized) NOT RUN (dispatch blocked). Analysis with recorded data:
  qwen2.5:7b (already Q4_K_M quantized in Ollama) probed 271.5 s/q → 362 min
  > 330-min cap. A same-class quantized replacement (qwen3:8b Q4_K_M ~5.2 GB,
  the closest existing model to the user's "qwen 3.8"; "Gemma4" does not
  exist — Gemma 3 ships 1b/4b/12b/27b, no 7b) is UNLIKELY to fit one job
  either (similar size class). Options: (a) two serialized 40-question runs
  (~185 min each, fits; disclosed protocol deviation, combined scoring at
  merge), (b) user-run via the runbook in engine/eval/README.md, (c) accept
  7b = pending user-run. qwen3:8b also emits <think> blocks unless disabled —
  a 5-question probe MUST precede any full run; if thinking output makes
  answers dirty, the model is unusable without a prompt/engine change
  (frozen) and (b)/(c) remain.
- Artifacts added this session: f2_pooled_PA.json, f2_pooled_NP.json,
  a6_parity.json (regenerated with battery), f5_per_category.json,
  pr-bodies-f1.md.

## 12. F-order execution session (2026-10-31 ~17:40Z+, fresh token) — PUSHED, PRs OPEN

Token restored by the user ("keep using the same token for now" = this new
one). Everything from §11 that was local-only is now on origin. All pushes
fast-forward; no force, no tags, no releases. No frozen ref moved.

- PUSHED (verified by push output): bench/local-results (NEW branch @ ce77f49),
  bench/extra-1 697458c..76454a0, bench/scale-1 9dd65d2..9125bbb
  (= 3ffedaf zipf mode + b9578c2 ci wiring + 9125bbb kwic repro),
  bench/t6-report 9f16790..a0b3283, bench/state 69213e8..f35d511 (+this commit).
- PRS OPENED (bot opened, none merged): #58 = bench/snapshot-run-41202610042
  (3b #3 snapshot — the PR step had never produced it), #59 = bench/local-results
  (raw run envelopes), #60 = bench/extra-1 (F2+F3 eval), #61 = bench/scale-1
  (F4 zipf + repetitive labeling). PR #57 head advanced to a0b3283 (F5 report
  corrections are on #57 — no new PR needed).
- DIFF GATES re-verified THIS session, all 0 lines:
  `git diff ee42bfa <SHA> -- engine ':!engine/eval'` for
  ce77f49, 76454a0, 3ffedaf, a0b3283; additionally full `-- engine`
  (including eval) = 0 lines for data-only ce77f49.
- KWIC limit-1000 FAILURE RUN ID FOUND (F4 evidence complete): run
  **41202901041** (workflow_dispatch, bench/scale-1 @ c02b3c7, 12:50:46Z),
  job "Scale (1000000 tokens)" FAILED at 12:58:17Z with
  `sqlite3.OperationalError: Expression tree is too large (maximum depth
  1000)` (sqlalchemy.exc.OperationalError wrap); the "Scale (10000000
  tokens)" leg was then cancelled. Logs downloaded and grepped this session.
  The failure is DETERMINISTIC (local repro scripts/kwic_repro.py on
  bench/scale-1 @ 9125bbb; 1200 distinct one-'the' sentences: limit=400 OK,
  limit=1000 raises). ACTION for #57: replace the "intermittent" wording
  with deterministic + this run ID (follow-up docs commit, with the zipf
  numbers below).
- ci(scale) wiring (b9578c2, on bench/scale-1): the Scale job previously
  called benchmark_scale.py WITHOUT --corpus-mode, so a dispatch would have
  re-run the repetitive mode. Added inputs.scale_corpus_mode (default
  repetitive) passed as flag + env fallback (script default now reads
  CORPUSMIND_SCALE_CORPUS_MODE). Gate re-verified 0 lines.
- F4 ZIPF DISPATCH: first dispatch attempt correctly REFUSED by the poll
  rule (pull_request CI runs in flight on bench/scale-1 head b9578c2;
  concurrency-safe wait). After the 9125bbb PR runs finished SUCCESS and the
  ref was idle (0 in-flight), DISPATCHED: run **41226973126** (queued
  2026-10-31 ~18:05Z, workflow_dispatch, bench/scale-1 @ 9125bbb,
  grounding_only="SCALE", scale_corpus_mode="zipf", run_grounding=false,
  commit_results=false). On completion: download artifacts scale-1000000 /
  scale-10000000, archive to bench-state/artifacts/f4-scale-zipf/{1m,10m}/,
  record ingest tok/s, KWIC zw1/zw2 wall + hits + the @1000 ceiling probe,
  keyness counts, peak RSS; then update BENCHMARK_REPORT.md §7 on #57
  (zipf numbers + KWIC "deterministic, run 41202901041" wording + F6
  approval-request subsection) and append results here.
- (F4) ZIPF RESULTS — RUN 41226973126 COMPLETED SUCCESS 2026-10-31 (~19:5xZ,
  both matrix legs). Artifacts archived bench-state/artifacts/f4-scale-zipf/.
  1M leg: 1,000 docs / 1,000,000 tokens / input_types 140,543; ingest
  439.5 s = 2,389 tok/s (degraded=false); KWIC zw1@400 3.35 s (138,190
  hits), zw2@400 4.99 s (61,759), zw1@1000 probe 7.83 s OK; keyness 0.98 s
  +100/−100; peak RSS 293 MiB. 10M leg: 10,000 docs / 10,000,000 tokens /
  input_types 219,934 (220k vocab fully realized — F4 "200k+ types" MET);
  ingest 4,364.3 s = 2,303 tok/s (degraded=false); KWIC zw1@400 53.06 s
  (1,377,841 hits), zw2@400 44.86 s (621,088), zw1@1000 probe 78.37 s OK;
  keyness 11.91 s +100/−100 (top zw266/269/316); peak RSS 666 MiB.
  READING: ingest throughput ~flat 1M→10M on zipf (vs the ~30% drop on
  repetitive); peak RSS tracks TYPE INVENTORY (234→220k types ⇒
  287→666 MiB at 10M), not token count — no OOM risk either way. The
  @1000 ceiling probe passed at all four measured scales — the depth-1000
  ceiling is reached by DISTINCT MATCHES, not corpus size.
- (F5 follow-up on #57) docs commit on bench/t6-report (after a0b3283):
  §7 zipf table + refined finding 1 (memory tracks inventory), finding 3
  rewritten deterministic + run 41202901041 (was "intermittent", no ID),
  finding 4 = F6 approval-request list (MTLD aggregation, KWIC or_() 400
  chunking), §8 provenance updated (#58–#61, zipf artifacts path).
- F-ORDER FINAL STATUS: F1 DONE (PRs #58–#61 open + merge order), F2 DONE,
  F3 DONE, F4 DONE (code+evidence+dispatch+results), F5 DONE, F6 LISTED
  (approval pending, nothing implemented). 7b: stays PENDING USER-RUN
  (probe 41206910830: 271.5 s/q ⇒ 362 min full-80 > 330-min cap; options
  in §11). Nothing merged by the bot at any point.
- F3 re-verified from the artifact: battery n_tables=2628 measure-rows over
  876 tables (chi2 n_comp 795 / G2 795 / OR 651; excluded 81/81/225 counted,
  not folded); compare() emits status NOT_TESTED with null maxima (code
  grep 76454a0 lines 119-139, 243-246); STTR short-corpus case documented
  "on the snapshot set alone this measure is NOT_TESTED" with the synth
  10k/50k/100k texts providing the comparables (max_rel 2.6e-3, disclosed
  LR last-segment discard).
- F2 re-verified from artifacts: pooled PA 222 docs / 163,609 tokens,
  boundary_errors 6,313, convention "gold minus engine", two-token CQL
  bigram table present (e.g. "العفريت فمن" freq 2 with 2 gold crossings).
- 7b (user ask: "quantized 7b such as qwen 3.8 or Gemma4"): still
  DOES-NOT-FIT per the pre-registered rule — qwen2.5:7b (already Q4_K_M)
  probed 271.5 s/q → 362 min full-80 > 330-min cap (probe 41206910830, 5/5
  clean). "Gemma4" does not exist (Gemma 3 = 1b/4b/12b/27b); closest to
  "qwen 3.8" is qwen3:8b Q4_K_M, same size class, <think> blocks risk dirty
  answers without a frozen-prompt change. Standing options for the user:
  (a) two serialized 40-question runs ~185 min each (protocol deviation,
  disclosed), (b) user-run via engine/eval/README.md runbook, (c) keep
  7b = PENDING USER-RUN. Nothing dispatched without user choice.
- MERGE ORDER (proposal; maintainer merges — bot must not): #50 → #51 →
  #52 → #53 → #54 → #55 → #56 → #58 (snapshots) → #59 (raw envelopes) →
  #60 (eval F2/F3) → #61 (scale F4) → #57 LAST (report, lands with its
  artifacts/tooling). Rationale: data snapshots first, then tooling that
  interprets them, report last so citations resolve.

## 13. Release-eve session (2026-11-01) — v2.0.2, merges authorized, F7 CONFIRMED

User authorized the merge order (this session): #50–#56, #58, #59, #60, #61,
then #57 LAST; then bring release/2.0.2 (#62) up to date, re-run the three
gates + CI, add the 7b data, and tag. Tag/release discipline per the release
work order (annotated tag, no force, no deletion).

- F7 CONFIRMED (2026-11-01, offline measurement on the sandbox machine):
  the grounding turn-1 prompt = ~5,221 Qwen2.5 tokens (SYSTEM_PROMPT 1,029 +
  corpus hint + context block + tool schemas 4,095 + question ≤36); pass 2
  with 3 summarized tool results ~7,576. Ollama default context = 4k tokens
  for <24 GiB VRAM (docs.ollama.com/context-length, 2026-10-27); CI runner
  is CPU-only (log: "No NVIDIA/AMD GPU detected"; client 0.40.13) ⇒ 4k
  default applied ⇒ EVERY CI local grounding run (1.5b ×3, 3b ×3, 7b probe)
  served truncated prompts. Rows = capability+truncation confound; triple
  stats remain internally valid. Re-run decision = maintainer's. Per-run
  truncation boundaries UNVERIFIED (server logs not archived). Disclosures:
  BENCHMARK_REPORT.md §4 F7 + §7 finding 4 (num_ctx fix = third
  post-freeze proposal); engine/eval/README.md §4 runbook now sets
  OLLAMA_CONTEXT_LENGTH=8192; data-branch README records it.
- 7b probe SCORED (offline vs frozen gold): G-001..G-005 → 0 PASS, 2
  MISSING_NUMBER, 2 HALLUCINATED, 1 TRAP_FAILURE. Scored report committed
  to bench/local-results (paper_report_7b_probe.json) with the NO_ANSWER
  caveat (aggregates over 80 include never-asked questions).
- Runbook fixed per user report (flags --chat-deadline/--grounding-only do
  not exist; GH_TOKEN never read): rewritten against the real argparse
  (bench/extra-1 4fda1a9 + cd9f96c). NOTE: the user's message referenced
  "Section 2 below can replace it" and "Step 6 below tests it cheaply" —
  those numbered sections did not arrive in the delivered message; both were
  reconstructed from the frozen code and labeled as such in the final reply.
- 7b "data PR (sections 2 and 3)": implemented as (a) scored probe report +
  F7 disclosure on bench/local-results (c33ac35, #59) and (b) report §4/§7/
  §8 updates on bench/t6-report (35e9509, #57). If the user meant NEW
  full-80 7b data from their own run, it was not in the message.

## 14. v2.0.2 RELEASED (2026-11-01, same session as §13)

- Merge chain EXECUTED with green CI before each merge: #50 → #51 → #52 →
  #53 → #54 → #55 → #56 → #58 → #61 → #59 → #60 → #57 (LAST). #60 needed two
  pre-merge fixes (ruff 0.17 B023/I001, commit a664a81) and main needed the
  follow-up mypy-strict PR #63 (eval 0 -> 13 -> 0 locally; non-blocking job).
- release/2.0.2 (#62) merged main twice; gates re-verified after each: gold
  sha256 480f5230…; benchmarks/results + manifest 0 lines vs main;
  engine diff vs ee42bfa = version constants only.
- PR #62 merged; ANNOTATED tag v2.0.2 created on merge commit 5a5e43f
  (no force, no deletions). Release run 41273493410 SUCCESS: preflight +
  test-gate green, 4 platform builds green, checksums job green.
- Release 430370346 published; PRERELEASE=TRUE set by release ID (work-order
  step 8; do NOT promote to stable until the user says so). Assets (9):
  nsis exe + msi, arm64+x64 dmg, deb + AppImage, web zip, EN guide PDF,
  SHA256SUMS.txt (AR guide not a release asset — matches the v2.0.1
  pattern; it ships in the repo / download/).
- Checksums verified: guide PDF, web zip, amd64 .deb match SHA256SUMS byte
  for byte; the other 6 assets UNVERIFIED byte-level (CI-generated from the
  uploaded set). Bundled engine 2.0.2: cited from the release smoke-test +
  test-gate jobs (green) and the committed version surfaces; direct
  installer introspection UNVERIFIED.
- Zenodo minted version DOI 10.5281/zenodo.23852351 (concept 23216073
  unchanged). Docs PRs open: #64 (README version-DOI row), #65 (report §9
  measured-at SHAs + release statement). NOT merged by the bot.
- Step 12 PROPOSAL (dry run + manifest only, NOTHING applied):
  scripts/retire_release_assets.py has v2.0.0/v2.0.1 in its hard-coded
  KEEP_TAGS, so it will never retire them as-is; while v2.0.2 is
  prerelease-flagged the tool's default plan targets V2.0.2's own
  installers — do NOT run --apply before promoting v2.0.2 to stable.
  Proposed change (user approval): drop v2.0.0/v2.0.1 from KEEP_TAGS, then
  dry-run + --apply; README download links -> releases/latest (resolves to
  the latest STABLE — i.e. v2.0.1 until promotion).
- F7/7b recap: F7 CONFIRMED (§13); 7b probe scored (0/5 passable); runbook
  fixed. F-order is DONE; the three post-freeze engine fixes (MTLD, KWIC
  or_(), num_ctx) remain PROPOSED, NOT MADE.
