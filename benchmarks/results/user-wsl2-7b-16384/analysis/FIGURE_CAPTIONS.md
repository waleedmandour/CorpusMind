# FIGURE_CAPTIONS.md — manuscript-ready captions (b7_16k user run)

**Figure 1. Verdict composition per repetition.** Stacked composition of repo-scorer
verdicts for the 80 grounding questions in each of the three repetitions of the
qwen2.5:7b @16384 user run (WSL2, CPU-only, 900 s per-question deadline). HALLUCINATED
(34/35/31) is the dominant outcome class in every repetition; NO_ANSWER rows are the
HTTP 502 deadline misses (2/3/4). Verdicts produced by `engine/eval/score.py` against
the frozen gold (sha256 480f5230...).

**Figure 2. PASS rate per repetition with Wilson 95% confidence intervals.**
Rep 1: 21/80 (26.2%), rep 2: 21/80 (26.2%), rep 3: 23/80 (28.7%); pooled over the
240 question-attempts: 65/240 = 27.1% (Wilson 95% CI 21.9-33.0). The rep-2 pool
uses the as-run shards; applying the pre-registered G-035 rescue does not change
the PASS count (Section 2 of RESULTS_SUMMARY).

**Figure 3. Question-level verdicts across the three repetitions.** Each row is one
of the 80 questions; columns are repetitions; colour is the repo-scorer verdict.
Rows are grouped by the number of repetitions in which the question PASSES:
16 questions pass all three reps, 4 pass exactly two, 9 exactly one, and 51 never
pass. The 58 rows with one single colour are verdict-identical across reps.

**Figure 4. Category-level pass rates.** Repo-scorer PASS rate within each of the
14 benchmark categories, per repetition (n = questions per category). Sentiment
(4/5), pos_grammar (2/3) and dispersion (4/7) pass in every repetition; CQL (0/6),
diversity (0/7) and discourse (0/3) never pass. kwic rises from 3/7 (reps 1-2) to
5/7 in rep 3; arabic_tools falls from 1/4 to 0/4.

**Figure 5. Per-question latency, answered vs failed.** Log-scale seconds per
question. Blue: 231 answered question-attempts (elapsed_ms; median ~172 s,
p95 <= 305 s, max 335 s). Orange: the nine NO_ANSWER records (wall_ms of the failed
harness attempt; all HTTP 502), which all exceed 1,375 s - far beyond the 900 s
per-question deadline - reflecting the engine's hardcoded 3 x 60 s tool-round
timeouts multiplied by harness re-sends. G-032 and G-077 fail in all three reps;
G-035 (rep 2) was rescued; G-008 and G-018 are rep-3-only misses.

**Figure 6. Repetition stability.** (a) Number of repetitions in which each question
PASSES (0/1/2/3 of 3). (b) Pairwise agreement between repetitions: exact
five-class verdict agreement (82.5%, 81.2%, 76.2%) and binary PASS agreement
(92.5%, 90.0%, 85.0%), with Cohen's kappa for the binary PASS outcome
(k = 0.81, 0.75, 0.62). This is the only local row in the project with n=3.

**Figure 7. PASS rate across local context arms.** Each dot is one run scored with
the repo scorer. Grey: eight CI runs of qwen2.5 1.5b/3b under the Ollama default
4k context (prompt truncation; F7). Green: the CI 16k arms (1.5b: 15/80, n=1;
3b: 18/80, n=1). Blue: the three repetitions of the 7b @16384 user run (21, 21, 23
of 80); the diamond marks the pooled rate 65/240 = 27.1% with Wilson 95% CI
(21.9-33.0). Caveats: CI arms use a 300 s per-question deadline vs 900 s for the
user run; 16k CI arms are n=1; no size ordering is claimed at 4k.
