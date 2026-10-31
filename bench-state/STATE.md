# CorpusMind BENCHMARKING — frozen-row state

Read this file FIRST every session and every scheduled turn. Do not act before
checking §7 (next action) and §8 (binding rules). Never put secrets in this file.

Last updated: 2026-10-31T12:55Z (A6 DONE on bench/extra-1 @ 62af13c; A7 scale run 41202459225 in flight on bench/scale-1 @ fcdab4f; A3: 3b#2 recorded, 3b#3 run 41202610042 in flight; 1.5b triple wrapped: flips 16/80)

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

- `corpusmind-gemini-daily` — 00:45 America/Los_Angeles — id 489478 (recreated 2026-10-31 per addendum; its first fire at 00:45 PDT 10-31 failed with 'model concurrency limit exceeded' — slice-1 was dispatched manually instead; next fire 2026-11-01T00:45-07:00)
- `corpusmind-gemini-drip` — 15:30 America/Los_Angeles — id 489479 (recreated 2026-10-31), next fire 2026-10-31T15:30-07:00
- (old IDs 489079/489080 were NOT found in this scheduler on 2026-10-31; these
  two jobs are their replacements)

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
    5. 3b #3 — 41202610042 IN FLIGHT since 12:46:46Z (bench/freeze-1-local
       @ ee42bfa, qwen2.5:3b, full 80, commit_results=true). On completion:
       fetch grounding-report, verify run_meta model, record, then the 7b
       probe per the step-6 rule.
    6. 7b probe (5 questions, commit_results=false, grounding_only
       'G-001 G-002 G-003 G-004 G-005') -> full 7b only if projection <= 330
       min; if it fits: 7b #1, #2, #3; if not: one-command runbook in
       engine/eval/README.md (on bench/extra-1, never a freeze ref) and mark
       the 7b row 'pending user-run'.
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

- (A7) IN FLIGHT. scripts/benchmark_scale.py + a gated `scale` job inside
  .github/workflows/benchmarks.yml on new branch bench/scale-1
  (@ fcdab4f, at ee42bfa; engine-diff rule 0 lines). NOTE: a new workflow
  file on a side branch is NOT dispatchable via the API (GitHub registers
  workflows from the default branch only — dispatch of scale.yml returned
  404), so the job piggybacks on the already-dispatchable benchmarks.yml,
  gated on `inputs.grounding_only == 'SCALE'` (schema-compatible with
  main; run_grounding stays false so no Gemini quota is used; the
  unconditional perf-arabic + seg-araseg jobs run as usual noise).
  Dispatched run 41202459225 on bench/scale-1 (matrix 1M / 10M tokens,
  parallel legs, each on a fresh SQLite file, timeout 350 min). Measures:
  ingest (ingestion.service.ingest_document, spaCy en_core_web_sm-3.8.0
  pinned), KWIC (search_concordance, word level, window 5), keyness
  (compute_keyness vs a 50k-token reference corpus) — wall time + peak RSS
  (ru_maxrss). Corpus: SYNTHETIC cycled frozen en-snapshot sentences
  (~1000 tok/doc; vocabulary ~234 types) — stated in _meta. Smoke-tested
  locally at 3k tokens before dispatch.

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
- docs/BENCHMARK_IMPROVEMENT_PLAN.md section 5 still says "PAID key" — user
  decision: the Gemini row is FREE-TIER BY DESIGN. Fix goes into the final
  docs-only PR (T6), not into any freeze ref.
- Brief said canonical seg snapshot was @ 06de47b; the actual snapshot run
  40970859593 is @ 57be77f. Superseded either way by §9(seg).
- The workflow's "Open snapshot PR" step silently failed for runs 41173011756
  and 41173022988 (step reports success via `|| echo`; no PR exists). Open the
  data-only snapshot PRs manually at merge time.
- Oct-30 20:42-21:58Z dispatch runs (4 in §3) were not in the original brief;
  all 0 clean, two off-spec models. No bank impact.
