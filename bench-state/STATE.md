# CorpusMind BENCHMARKING — frozen-row state

Read this file FIRST every session and every scheduled turn. Do not act before
checking §7 (next action) and §8 (binding rules). Never put secrets in this file.

Last updated: 2026-10-31T05:45Z (setup session: T0–T4a done, crawl jobs armed)

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
| G-004 | RE-ASK  | 41026068623 (08:23Z) | afce8fe | 1936 lines                                   | NO — re-ask           |
| G-040 | RE-ASK  | 41026068623 (08:23Z) | afce8fe | 1936 lines                                   | NO — re-ask           |
| G-073 | RE-ASK  | 41051082943 (11:51Z) | 9c272b8 | 94 lines (tests-only: engine/tests/test_phase3_arabic.py) | NO — re-ask (literal rule) |

- Probe-run answers G-004/G-040 scored PASS and G-004 was an honest-trap fail —
  none of that carries over: gold was re-frozen in #43/#44 and the diff rule
  above is applied literally. Their freeze-row status will be whatever the
  re-ask produces.
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
| 2026-10-31 | slice-1 | (see §7) | bench/freeze-1 | §5 list, first 16 | — | — | pending |

## 5. Crawl queue (unbanked order for bench/freeze-1)

Re-asks first, then bank order. Banked-for-freeze so far: G-001, G-002.

1. slice-1 (≤16): G-004 G-040 G-073 G-003 G-005 G-006 G-007 G-008 G-009 G-010 G-011 G-012 G-013 G-014 G-015 G-016
2. drip (≤4): retry infra-dirty of slice-1 (max 4); if none, advance: G-017 G-018 G-019 G-020
3. then in order: G-021 … G-039, G-041 … G-072, G-074 … G-080 (60 remaining after today)

Slice sizing rule: never exceed 20 dispatched questions per Pacific day across
both slices (16 morning + 4 drip). If the observed quota is tighter (see §10),
shrink to what succeeds and update this file.

## 6. Schedule

- `corpusmind-gemini-daily` — 00:45 America/Los_Angeles (after Pacific reset) — id: see scheduler
- `corpusmind-gemini-drip` — 15:30 America/Los_Angeles — id: see scheduler
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
  committed "canonical" snapshot — SUPERSEDED by: run 41173011756 on
  bench/freeze-1-seg (seg_limit=20, run_grounding=false, run_gold_diff=true,
  commit_results=true) — result: PENDING, update on completion. Do NOT run the
  test split.
- (local-a) qwen2.5:1.5b re-run on freeze: run 41173022988 on bench/freeze-1-local
  (full 80, commit_results=true) — PENDING. On success, mark 41028985957
  superseded. Prior row (to be replaced): pass 0.1375, hallucination 0.65
  (UNVERIFIED here; verify by re-scoring the new run).
- (local-b) larger local model: NOT STARTED. Procedure: after (a) completes and
  bench/freeze-1-local is idle, dispatch qwen2.5:3b with grounding_only =
  "G-001 G-002 G-003 G-004 G-005" (5 questions), same ollama params as (a),
  commit_results=false. Wall-time projection = elapsed × 16; run the full bank
  only if projection ≤ 330 min (runner cap 360). Then try qwen2.5:7b the same
  way. If neither fits: write a one-command runbook in engine/eval/README.md
  (on a bench branch, not the freeze refs) and mark the row "pending user-run".
- (gemini) IN PROGRESS: banked 2/80 reusable (+3 re-asks queued). ~5-8 Pacific
  days at 16+4/day if clean; re-check §5 every turn.

## 10. Known anomalies / open items for the report

- Oct-30 quota accounting is inconsistent with a plain 20/day pool (79×429 at
  12:27Z, then a clean G-002 at 20:06Z the same Pacific day). Treat slices as
  adaptive: never exceed 20/day, shrink if 429 walls appear early.
- Two off-spec model attempts happened Oct-30 evening (flash-lite, pro) — see
  §3; zero clean answers, disclosed.
- docs/BENCHMARK_IMPROVEMENT_PLAN.md section 5 still says "PAID key" — user
  decision: the Gemini row is FREE-TIER BY DESIGN. Fix goes into the final
  docs-only PR (T6), not into any freeze ref.
- Brief said canonical seg snapshot was @ 06de47b; the actual snapshot run
  40970859593 is @ 57be77f. Superseded either way by §9(seg).
