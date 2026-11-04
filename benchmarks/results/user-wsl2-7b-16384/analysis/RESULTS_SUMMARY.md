# RESULTS_SUMMARY — user-run Tier B: qwen2.5:7b @16384 (WSL2), three repetitions

**Scope.** Faithful analysis of the committed artifacts under
`benchmarks/results/user-wsl2-7b-16384/` (12 shards = 3 reps x 20 disjoint questions,
union G-001..G-080 per rep; 5 rescue records; G-001 retest; 5-question probe; logs).
Every verdict below was produced by the **repo scorer** (`engine/eval/score.py`,
frozen gold `480f5230...`) on the per-rep **merged** shards, using the repo's own
`scripts/validate_user_run.py` protocol (gold-hash check, disjointness/union check,
merge, repo score, independent re-score cross-check, CI flip comparison).
The validator's structural gate: **STRUCTURAL: PASS** for all three repetitions.

**Run identity.** Ollama 0.40.13, `OLLAMA_CONTEXT_LENGTH=16384`, engine v2.0.2 at
`5a5e43f` (frozen, unchanged across reps), CPU-only WSL2 (Ubuntu 24.04 on Windows 11),
per-question deadline 900 s, `--rate-retries 4`, r1 started 2026-11-02T18:11Z,
r2 2026-11-02T20:32Z, r3 stopped 2026-11-04T12:35Z. This row removes the F7
truncation confound of the CI local runs (Ollama default 4k context); the
truncation gate over the server log segments reported 0 truncated prompts.

## 1. Headline: PASS rate (repo scorer, as-run)

| repetition | PASS | n | rate | Wilson 95% CI |
|---|---|---|---|---|
| rep 1 | 21 | 80 | 26.2% | [17.9, 36.8] |
| rep 2 | 21 | 80 | 26.2% | [17.9, 36.8] |
| rep 3 | 23 | 80 | 28.7% | [20.0, 39.5] |
| **pooled (3 reps)** | **65** | **240** | **27.1%** | [21.9, 33.0] |

Verdict composition (as-run, questions per rep of 80):

| repetition | PASS | MISSING_NUMBER | HALLUCINATED | TRAP_FAILURE | NO_ANSWER |
|---|---|---|---|---|---|
| rep 1 | 21 | 13 | 34 | 10 | 2 |
| rep 2 | 21 | 11 | 35 | 10 | 3 |
| rep 3 | 23 | 11 | 31 | 11 | 4 |

HALLUCINATED (a quoted number absent from every tool output for the question) is the
dominant failure class in all three reps (34/35/31
of 80), consistent with the CI arms' flag-level pattern at 4k and 16k alike.

## 2. Rescue application (pre-registered rule)

The G-035 (rep 2) rescue succeeded operationally and was applied per the
pre-registered rule: the failed 502 record is replaced by the rescue record
(333.7 s, 2 tool calls). **The rescue recovered availability, not correctness**:
the repo scorer marks the rescued answer **HALLUCINATED**, so the rep-2 PASS count
is unchanged (21) and only the NO_ANSWER count drops 3 -> 2.

Rescue-applied verdict counts (rep 2 only row shown where it differs): PASS 21,
MISSING_NUMBER 11, HALLUCINATED 36, TRAP_FAILURE 10, NO_ANSWER 2.

The four remaining rescue attempts (G-032 and G-077 in reps 1 and 2) failed again
with the 497-byte error-stub signature and were **stopped per the pre-registered
protocol**; the questions are disclosed as deadline-limited misses. No rescues were
attempted in rep 3.

## 3. NO_ANSWER inventory (9 records across 240 attempts, all HTTP 502)

| question | rep | wall s | outcome |
|---|---|---|---|
| G-032 | rep 1 | 1888.1 | rescue also failed (r1, r2); deterministic miss |
| G-077 | rep 1 | 1432.0 | rescue also failed (r1, r2); deterministic miss |
| G-032 | rep 2 | 1853.5 | rescue also failed (r1, r2); deterministic miss |
| G-035 | rep 2 | 1908.4 | rescued -> HALLUCINATED |
| G-077 | rep 2 | 1430.5 | rescue also failed (r1, r2); deterministic miss |
| G-008 | rep 3 | 1377.9 | disclosed miss (r3 only) |
| G-018 | rep 3 | 1963.7 | disclosed miss (r3 only) |
| G-032 | rep 3 | 1964.8 | rescue also failed (r1, r2); deterministic miss |
| G-077 | rep 3 | 1584.9 | rescue also failed (r1, r2); deterministic miss |

- **G-032** failed in all 3 reps and **G-077** in all 3 reps - deterministic
  deadline misses (per-question 900 s cap; engine's hardcoded 3 x 60 s tool-round
  timeout x harness re-sends produces the observed ~1,400-1,965 s walls).
- **G-008** and **G-018** are rep-3-only misses (rep 1/2 answered them at
  305.0 s / 851.5 s mean wall respectively - slow but inside the deadline).
- All nine records carry empty answers and `http_status: 502`
  ("Model call failed: [ollama] chat request failed").

## 4. Repetition stability (the only n=3 local row in the project)

| statistic | value |
|---|---|
| identical verdict in all 3 reps | 58 / 80 questions |
| PASS in all 3 reps | 16 |
| PASS in >= 2 of 3 (majority) | 20 |
| PASS in >= 1 of 3 | 29 |
| never PASS | 51 |
| exact verdict agreement r1-r2 / r1-r3 / r2-r3 | 82.5% / 81.2% / 76.2% |
| PASS / not-PASS agreement | 92.5% / 90.0% / 85.0% |
| Cohen's kappa (PASS binary) | 0.8063 / 0.7494 / 0.6241 |

The 16 three-rep PASS questions are the stable skill core:
G-001, G-017, G-020, G-021, G-034, G-039, G-040, G-042, G-045, G-053, G-054, G-055, G-057, G-070, G-071, G-076.

Harness `grounded` flag (answer carries tool evidence): 77/80, 76/80, 75/80.
G-027 is the zero-tool question and is never flagged; the other unflagged records
are the 502 misses.

## 5. Latency and tool behaviour

| repetition | answered n | median s | mean s | p95 s | max s |
|---|---|---|---|---|---|
| rep 1 | 78 | 174.8 | 175.6 | 305.0 | 335.1 |
| rep 2 | 77 | 171.8 | 176.7 | 261.8 | 320.2 |
| rep 3 | 76 | 172.1 | 169.8 | 283.3 | 332.2 |

Pearson correlation of per-question elapsed time across reps (75 questions answered
in all reps): r1-r2 0.74, r1-r3 0.657, r2-r3 0.614 - question difficulty
dominates over run-to-run noise. Tool calls per answered question: mean
1.08 / 1.05 / 1.07 (median 1, max 2); exactly one zero-tool
question per rep (G-027). Failed tool rounds (tool_calls with ok=false): 5 / 7 / 6.

## 6. Category profile (repo scorer, as-run)

| category | n | rep 1 | rep 2 | rep 3 |
|---|---|---|---|---|
| sentiment | 5 | 80.0% | 80.0% | 80.0% |
| pos_grammar | 3 | 66.7% | 66.7% | 66.7% |
| dispersion | 7 | 57.1% | 57.1% | 57.1% |
| kwic | 7 | 42.9% | 42.9% | 71.4% |
| ngrams | 4 | 25.0% | 25.0% | 25.0% |
| trap | 8 | 25.0% | 25.0% | 25.0% |
| collocation | 6 | 16.7% | 33.3% | 16.7% |
| corpus_stats | 5 | 20.0% | 20.0% | 20.0% |
| keyness | 10 | 20.0% | 10.0% | 20.0% |
| register | 5 | 0.0% | 20.0% | 20.0% |
| arabic_tools | 4 | 25.0% | 0.0% | 0.0% |
| cql | 6 | 0.0% | 0.0% | 0.0% |
| discourse | 3 | 0.0% | 0.0% | 0.0% |
| diversity | 7 | 0.0% | 0.0% | 0.0% |

Stable strengths: sentiment (4/5 in every rep), pos_grammar (2/3), dispersion (4/7).
Stable zeros: cql (0/6), diversity (0/7), discourse (0/3) - the model cannot compose
CQL queries or report diversity/discourse measures in this harness. kwic improved in
rep 3 (3/7 -> 5/7); arabic_tools regressed to 0 after rep 1 (1/4 -> 0/4).

## 7. Context arm comparison (CI rows, committed paper_report.json)

| arm | PASS / 80 |
|---|---|
| 1.5b @4k (freeze triple, n=3) | 13 / 12 / 12 |
| 3b @4k (freeze triple + P1 confirm + pinned control) | 6 / 6 / 5 / 4 / 4 |
| 1.5b @16384 (n=1) | 15 |
| 3b @16384 (n=1) | 18 |
| **7b @16384 (this run, n=3)** | **21 / 21 / 23 (pooled 27.1%)** |

Reading (with the standing caveats): CI arms run a 300 s deadline and n=1 per 16k
arm; the user run allows 900 s. The 4k rows are measured under the F7 prompt
truncation. No size ordering is claimed between 1.5b and 3b at 4k (the ordering
reverses at 16k, Wilson CIs overlap). What the new row adds: at 7b and 16384 the
PASS rate rises to ~27% with three-rep stability (kappa 0.62-0.81), and the failure
mass shifts decisively to hallucinated numbers rather than missing ones.

## 8. Cross-checks and disclosures

- **Probe environment check.** Re-scoring `probe16k.json` in the analysis
  environment reproduces `probe16k.repo_scored.json` verdicts exactly
  (80/80 identical, including the 75 never-asked NO_ANSWER rows).
- **G-001 retest** (after the cold-start 502 in the probe): PASS at 173 s,
  matching PASS in all three reps - the probe's G-001 failure was cold-start
  model loading (3 x 60 s tool-round timeout), not a capability signal.
- **Independent re-score disagreements** (the validator's deliberately simpler
  second scorer): 15 / 12 / 18 questions differ per rep, mostly
  MISSING_NUMBER-vs-HALLUCINATED semantics; per protocol these are reported, not
  fatal, and the **repo scorer remains the citable verdict source** (identical
  logic applied to every CI arm, so comparability holds).
- **Environment files not yet in the repo**: `env_qwen2.5-7b.json`,
  `host_snapshot.txt`, the three `ollama_server` log segments, and
  `pip_freeze.txt` (created 2026-11-04). Upload when convenient; the analysis
  above does not depend on them.
- The run-folder `MANIFEST.json` currently hashes only the three probe-stage
  files; it should be regenerated over the full folder once the remaining
  evidence files land.
- Two placeholder-aborted invocations wrote junk files before production data;
  deleted before production data was collected. No shard was affected
  (per `evidence/notes.txt`, the reconstructed journal; the `*.log` files are
  the authoritative record).

## 9. Reproduce

```bash
# from a clone of the repo at de7025644 ("data(bench): relocate b7_16k Tier B
# run files into results/user-wsl2-7b-16384"):
python3 scripts/validate_user_run.py     --data-dir benchmarks/results/user-wsl2-7b-16384     --engine-dir engine     --ci-arm 41306198564 --ci-arm 41306208341 --ci-arm 41306203484
# merged + scored files land in <data-dir>/merged/; expected: STRUCTURAL: PASS
```

`metrics.json` (every number in this document) and `per_question.csv`
(240 rows: question x rep verdict, grounded, latency, tool calls) accompany this
summary; figures carry manuscript-ready captions in `FIGURE_CAPTIONS.md`.

## 10. Pre-registered context contrast, 3b — pinned 4k control vs 16384 (added 2026-11-05)

Computed per Plan v3 §7 from the two committed CI arms (`run-41306198564` control,
`run-41306203484` arm; both pinned Ollama 0.40.13, same frozen gold, repo scorer):
exact McNemar on the 80 paired per-question binary verdicts. Discordant pairs
b = 3 (PASS at 4k only), c = 17 (PASS at 16384 only) → **p = 0.00258, Holm-adjusted
p = 0.00258** (single executed test in the declared family) — the 16384 arm improves
3b grounding: 22.5% vs 5.0% PASS. Verdict-level: 9 questions move
MISSING_NUMBER → PASS, 12 move MISSING_NUMBER → HALLUCINATED (failure mass shifts
from missing to hallucinated, matching the 7b signature); traps are context-stable.
Full paired table, question IDs, and caveats (n=1 per arm; CI 300 s deadline):
`MCNEMAR_3b_CONTEXT_CONTRAST.md` + `stats_3b_context_contrast.json`.
The 1.5b context contrast and the size contrasts remain unexecuted (no clean
comparator / no bridging runs) — see `AREA_AUDIT.md`.
