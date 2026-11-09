# RESULTS_SUMMARY — user-run Tier B fallback arm: llama3.1:8b @16384 (WSL2), three repetitions

**Scope.** Faithful analysis of the committed artifacts under
`benchmarks/results/user-wsl2-llama3.1-8b-16384/` (12 shards = 3 reps × 20 disjoint
questions, union G-001..G-080 per rep; 2 rescue records; 5-question probe; logs;
gate evidence). Every verdict below was produced by the **repo scorer**
(`engine/eval/score.py` at the frozen commit `5a5e43fa`, gold sha256 `480f5230…`)
on the per-rep **merged** shards, following the `scripts/validate_user_run.py`
protocol (gold-hash check, disjointness/union check, merge, repo score, independent
re-score cross-check, CI flip comparison). The validator's structural gate:
**STRUCTURAL: PASS**. Re-running the repo scorer in this analysis environment
reproduces every committed verdict exactly (80/80 per rep, 80/80 scored probe rows;
`metrics.json → reproduce_rescore`).

**Run identity.** Ollama 0.40.13, `OLLAMA_CONTEXT_LENGTH=16384`, engine v2.0.2 at
`5a5e43fa` (frozen), CPU-only WSL2 (AMD Ryzen 5 4500U, 6 threads; same compute mode
as the committed qwen2.5:7b comparator), per-question deadline 900 s,
`--rate-retries 4`, three reps × four shards of 20, model warmed per rep. Gates 1–5
all PASS 2026-11-08 (`evidence/notes.txt`); arm choice (fallback llama3.1:8b after
the gemma4:e4b gate-out) written before the first repetition. Truncation gate over
the run server segments: 0 matches on both patterns
(`evidence/truncation_gate.txt`). r1 2026-11-08T17:24Z, r2 22:56Z, r3 03:58Z
(2026-11-09). Provenance and the post-run disclosures live in **addendum-2**
(`benchmarks/plans/2026-11-09_gemma4-e4b-arm-plan-v1-addendum-2.md`).

## 1. Headline: PASS rate (repo scorer, as-run)

| repetition | PASS | n | rate | Wilson 95% CI |
|---|---|---|---|---|
| rep 1 | 18 | 80 | 22.5% | [14.7, 32.8] |
| rep 2 | 21 | 80 | 26.2% | [17.9, 36.8] |
| rep 3 | 19 | 80 | 23.7% | [15.8, 34.1] |
| **majority (PASS in ≥2 of 3)** | **19** | **80** | **23.8%** | **[15.8, 34.1]** |

Verdict composition (as-run, questions per rep of 80):

| repetition | PASS | MISSING_NUMBER | HALLUCINATED | TRAP_FAILURE | NO_ANSWER |
|---|---|---|---|---|---|
| rep 1 | 18 | 25 | 23 | 13 | 1 |
| rep 2 | 21 | 22 | 26 | 11 | 0 |
| rep 3 | 19 | 22 | 24 | 14 | 1 |

Unlike the qwen2.5:7b arm (HALLUCINATED dominant: 34/35/31), the llama3.1:8b arm's
failure mass splits almost evenly between MISSING_NUMBER (22–25) and HALLUCINATED
(23–26), with a heavier TRAP_FAILURE tail (11–14 vs 10–11 on 7b). HALLUCINATED
share of attempts: 28.8% / 32.5% / 30.0%.

## 2. Confirmatory test: exact McNemar vs the pinned qwen2.5:7b majority vector

Per plan v1 §4 the only confirmatory test pairs this arm's majority vector against
the pinned `qwen7b_majority_vector.json` (sha256 verified `f36a02ec…` before
computation; qwen per-rep PASS 21/21/23, majority 20/80).

| | qwen not-PASS | qwen PASS | total |
|---|---|---|---|
| **llama PASS** | 7 (b) | 12 | 19 |
| **llama not-PASS** | 53 | 8 (c) | 61 |
| total | 60 | 20 | 80 |

- **b = 7** — llama-majority PASS only: G-018, G-023, G-051, G-056, G-068, G-069, G-074
- **c = 8** — qwen-majority PASS only: G-014, G-034, G-040, G-042, G-045, G-070, G-071, G-078

Exact two-sided McNemar: **p = 1.00** (raw). Holm over the declared five-test family
(the plan v1 extension): with two executed tests the step-down values are ctx×3b
0.0026 → **0.0129** and family×TierB (this test) → **1.00**. The disclosure pair of
plan v1 §4 applies verbatim: the 3b context contrast, published at m = 4 as 0.0103,
re-reports jointly at m = 5 as 0.0129 (conclusion unchanged); no post-hoc contrast
enters the family.

**Reading.** 19/80 vs 20/80 majority PASS, discordants split 7/8 — no detectable
difference at n = 80. Per plan v1 §4 this is "no detectable difference", never
evidence of equivalence; the arm's principal yield is descriptive.

## 3. Repetition stability

| statistic | value |
|---|---|
| exact five-class verdict agreement r1–r2 / r1–r3 / r2–r3 | 73.8% / 68.8% / 77.5% |
| PASS / not-PASS agreement | 93.8% / 91.3% / 92.5% |
| Cohen's κ (binary PASS) | 0.83 / 0.75 / 0.80 |
| PASS in all 3 reps | 15 |
| PASS in ≥1 of 3 | 24 |
| never PASS | 56 |

The 15 three-rep PASS questions: G-001, G-016, G-017, G-018, G-020, G-022, G-039,
G-053, G-054, G-055, G-056, G-057, G-068, G-069, G-074. Eight of the 15 are also in
the qwen 7b stable core (G-001, G-017, G-020, G-039, G-053, G-054, G-055, G-057);
the remaining seven (G-016, G-018, G-022, G-056, G-068, G-069, G-074) are
llama-only stable passes.

Harness `grounded` flag (answer carries tool evidence): 78/80, 79/80, 78/80.

## 4. Rescue application (pre-registered rule, plan v1 §3)

G-059 (the register-share question; the slowest item on CPU-only inference) ended
in HTTP 502 ReadTimeout in reps 1 and 3 (walls 1273.7 s and 1312.5 s); rep 2
answered it in 593.3 s. One rescue per errored record, per plan:

| rep | rescue outcome | wall | tools |
|---|---|---|---|
| rep 1 | **FAILED** — all 4 rate-retries exhausted on ReadTimeout → HTTP 502, empty answer; stopped per the pre-registered rule | 1385.4 s | none |
| rep 3 | **SUCCEEDED** on the 4th rate-retry — clean re-run with tools | 1210.8 s | get_corpus_overview, get_frequency |

Both attempts are kept (`rescues/l8_16k_r{1,3}_rescue_G-059.json`); no timeout was
changed. Per plan v1 §3 the clean rep-3 re-run "replaces the errored record in the
merge": the **rescue-applied variant** is committed as
`merged/l8_16k_r3_rescue_applied.scored.json`. The repo scorer marks the rescued
answer **HALLUCINATED** (it quotes 11 / 4.721% — tool numbers for a frequency
question whose gold expects the register shares 0.75 / 0.25 / 0.0), so the rep-3
PASS count is **unchanged** (19) and only NO_ANSWER drops 1 → 0
(HALLUCINATED 24 → 25). The as-run NO_ANSWER remains the verdict of record in the
merged files; the majority vector and the confirmatory test are identical under
both readings because G-059 is not-PASS either way (addendum-2 §A5).

## 5. NO_ANSWER inventory (2 records across 240 attempts, both HTTP 502)

| question | rep | wall s | outcome |
|---|---|---|---|
| G-059 | rep 1 | 1273.7 | rescue also failed; disclosed transport miss |
| G-059 | rep 2 | 593.3 | answered (max wall of rep 2) |
| G-059 | rep 3 | 1312.5 | rescued → HALLUCINATED (availability recovered, not correctness) |

Two of three reps missed G-059 on transport; rep 2 shows the item is inside the
deadline when the server keeps up. This matches the 7b arm's deadline-miss pattern
(G-032/G-077 there; a different, model-dependent miss set here — plan v1 §7).

## 6. Latency and tool behaviour

| repetition | answered n | wall median s | wall mean s | wall p95 s | wall max s | elapsed median s |
|---|---|---|---|---|---|---|
| rep 1 | 79 | 199.0 | 230.7 | 349.9 | 1036.7 | 184.6 |
| rep 2 | 80 | 191.3 | 217.5 | 310.5 | 593.3 | 184.0 |
| rep 3 | 79 | 201.8 | 219.2 | 337.7 | 684.3 | 181.9 |

66 / 69 / 69 of 80 answered questions took ≥180 s of wall time — CPU-only serving
is slow across the board (qwen2.5:7b medians were 171.8–174.8 s), and the
engine-side elapsed time is ~8–20 s below wall, so most overhead is serving, not
parsing. Tool calls per answered question: mean 1.03 / 1.04 / 1.03 (max 2).
**Failed tool rounds (tool_calls with ok=false): 39 / 44 / 43** — an order of
magnitude above the qwen arm's 5 / 7 / 6, i.e. llama3.1:8b's tool-call
argument formation fails far more often and the harness re-prompts.

Zero-tool questions: G-027 in every rep (the same never-tool question as the 7b
arm — a capability gap, not a trap; G-004, the no-tool trap, *does* call a tool and
fails the trap with numbers), plus G-059 in reps 1/3 (the 502 records). Shard
tool-call counts mirror this: shard2 has exactly 19/20 with-tool items in all three
reps (G-027), shard3 19/20 in reps 1/3 (G-059).

## 7. Category profile (repo scorer, as-run)

| category | n | rep 1 | rep 2 | rep 3 |
|---|---|---|---|---|
| sentiment | 5 | 100.0% | 100.0% | 100.0% |
| dispersion | 7 | 71.4% | 85.7% | 71.4% |
| discourse | 3 | 66.7% | 66.7% | 66.7% |
| corpus_stats | 5 | 40.0% | 20.0% | 20.0% |
| trap | 8 | 25.0% | 25.0% | 25.0% |
| ngrams | 4 | 25.0% | 25.0% | 25.0% |
| keyness | 10 | 10.0% | 20.0% | 10.0% |
| kwic | 7 | 0.0% | 14.3% | 0.0% |
| cql | 6 | 0.0% | 16.7% | 33.3% |
| pos_grammar | 3 | 0.0% | 0.0% | 0.0% |
| arabic_tools | 4 | 0.0% | 0.0% | 0.0% |
| collocation | 6 | 0.0% | 0.0% | 0.0% |
| register | 5 | 0.0% | 0.0% | 0.0% |
| diversity | 7 | 0.0% | 0.0% | 0.0% |

Per language: English 15/65, 19/65, 17/65; Arabic 3/15, 2/15, 2/15.

Family contrast, descriptive: the stable strengths partially replicate
(sentiment, dispersion, discourse) but the profile is **not** the 7b profile —
llama3.1:8b is at ceiling on sentiment (5/5 in every rep, vs 4/5 on 7b), collapses
on pos_grammar (0/3 vs 2/3), kwic (0–1/7 vs 3–5/7) and arabic_tools (0/4 vs 1/4 →
0/4), and cannot form collocation or register answers at all. Stable zeros shared
with 7b: cql (except one rep-3 hit), diversity, discourse.

## 8. Arm comparison (CI rows, committed paper_report.json)

| arm | PASS / 80 |
|---|---|
| qwen2.5:3b @4k (CI, n=1) | 4 |
| qwen2.5:3b @16384 (CI, n=1) | 18 |
| qwen2.5:1.5b @16384 (CI, n=1) | 15 |
| **qwen2.5:7b @16384 (Tier B, n=3, majority)** | **20** |
| **llama3.1:8b @16384 (this run, n=3, majority)** | **19** |

Descriptive McNemar (no significance language; the confirmatory pair is §2):
against run-41306203484 (3b @16k) the llama reps split 10/10 (rep 1), 12/9 (rep 2),
11/10 (rep 3) discordant pairs — the balanced 10/10 split is why two arms with
equal pass counts (18 vs 18) share almost no individual passes; against the 3b @4k
control the llama reps gain 16–18 and lose 1–2 (raw p 0.0001–0.0013, descriptive);
against 1.5b @16k, 12–14 vs 8–9. Full paired tables:
`stats_descriptive_ci_contrasts.json`.

## 9. Cross-checks and disclosures

- **Reproduce check.** Re-scoring the three committed merges and the probe in this
  analysis environment reproduces every committed verdict exactly (80/80 × 3 + probe).
- **Independent re-score disagreements** (the validator's deliberately simpler
  second scorer): 22 / 18 / 23 questions differ per rep
  (`scorer_diff.json`); dominant pattern MISSING_NUMBER → HALLUCINATED (10/11/9),
  i.e. the answer quotes numbers absent from the frozen tool universe where the
  repo scorer only missed gold numbers. **TRAP_FAILURE → PASS under the independent
  scorer: 2 / 1 / 4.** Per protocol these are reported, not fatal, and the repo
  scorer remains the citable verdict source (identical logic applied to every arm).
- **Corpus-totals hallucination signature** (`corpus_totals_hallucination.json`):
  in each rep the model asserts one fixed pair of wrong corpus totals that recurs
  across questions — rep 1 `98.0` (6 questions) and `529354.0` (2), rep 2 `8255.0`
  (7) and `3.0` (3), rep 3 `6.0` (5) and `4.0` (4) — against frozen gold totals of
  3 documents / 384 tokens (C1) and 4 / 233 (C4). The totals are re-invented per
  repetition, never retrieved.
- **Manifest regeneration.** `manifest.json` was regenerated over the full folder
  (lowercase, commit-under-test `5a5e43fa…`, run-url
  `local://Waleed-Desktop/WSL2-Ubuntu24.04-tierB-user-run`) after the analysis
  bundle was added, mirroring the 7b arm's convention; the superseded 52-file
  index covered only the pre-analysis bundle.
- **Post-run disclosures** (gate-4 self-test log pattern, gemma4 gate-out +
  fallback activation, G-059 rescue outcomes, post-run env-prefix incident):
  addendum-2 §A3–§A5,
  `benchmarks/plans/2026-11-09_gemma4-e4b-arm-plan-v1-addendum-2.md`.

## 10. Reproduce

```bash
# from a clone of github.com/waleedmandour/CorpusMind:
python3 scripts/validate_user_run.py \
    --data-dir benchmarks/results/user-wsl2-llama3.1-8b-16384 \
    --engine-dir engine \
    --ci-arm 41306198564 --ci-arm 41306203484 --ci-arm 41306208341
# expected: STRUCTURAL: PASS (merged + scored files land in <data-dir>/merged/)
```

`metrics.json` (every number in this document), `per_question.csv` (240 rows:
question × rep verdict, grounded, latency, tool calls), `llama31_majority_vector.json`
(plan v1 §4 pairing vector), `stats_confirmatory_mcnemar.json` (the confirmatory
test), `stats_descriptive_ci_contrasts.json`, `scorer_diff.json`,
`corpus_totals_hallucination.json`, and `g059_no_tool_inventory.json` accompany
this summary; figures carry manuscript-ready captions in `FIGURE_CAPTIONS.md`.
