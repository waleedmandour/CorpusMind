# Pre-specified plan: second local model-family arm (grounding benchmark, Tier B user run)

**Status: written before any measurement of this arm.** The commit timestamp of this
file on `github.com/waleedmandour/CorpusMind` is the record of when the plan was
fixed. Lineage: extends *CorpusMind Benchmark Re-run Plan v3* (1 November 2026,
project records) — the plan behind the committed 3b context contrast — with a second
model family. Nothing in Plan v3 is changed by this document; the extension is
additive and is itself fixed before the first shard of the new arm is run.

## 1. Question

Under the frozen grounding protocol and identical platform settings, do the
majority-vote pass rate and the verdict composition of a second model family differ
from those of the committed `qwen2.5:7b` arm? The failure-profile question is of
equal interest to the rate question: does the UNGROUNDED_NUMBER-dominated verdict
composition (41.7% of attempts on the 7B arm), the stable category profile
(sentiment/pos_grammar/dispersion passing; CQL, diversity and discourse at zero),
and the grounded-flag-not-fidelity pattern replicate across families?

## 2. Arm

- **Primary arm:** `gemma4:e4b-it-q4_K_M` (Ollama library; Gemma 4 E4B,
  instruction-tuned, Q4_K_M). The exact digest, quantisation level, parameter size,
  context window and capability list are recorded from `/api/show` (and `ollama ls`)
  before the first measurement and committed under
  `benchmarks/results/user-wsl2-gemma4-16384/evidence/`.
- **Why this model:** it is the Gemma-family model closest to the 7B serving class
  that Ollama serves with native tool calling (the harness needs the tool path), and
  E4B-class models are representative of what corpus linguists actually run on
  16 GB CPU-only machines. It has roughly 4.5B effective and about 8B total
  parameters (with embeddings). Size is therefore **not** matched to `qwen2.5:7b`
  (7.6B) in effective compute, and the paper will say so. "7B-class" in this study
  is defined by the 16 GB serving footprint, not by parameter count.
- **Fallback arm:** `llama3.1:8b`, used only if the pre-run gate (Section 5) fails
  for the primary arm. Exactly one arm is run in full. The choice is written to
  `notes.txt` before the first full repetition, and the outputs of any failed gate
  are committed as protocol evidence.

## 3. Fixed protocol (identical to the qwen2.5:7b user run)

- Engine v2.0.2, commit `5a5e43fa0c9e6a903dc06f79579b732a9f666bca`, unchanged; the
  frozen checkout on the run machine stays at this commit (fetch only, never pull).
- Gold `engine/eval/data/gold/grounding_gold.json`, sha256 prefix `480f5230`.
- Hardware: AMD Ryzen 5 4500U, CPU only, WSL2 Ubuntu 24.04, 16 GB RAM cap.
- Ollama 0.40.13 (no upgrade); `OLLAMA_CONTEXT_LENGTH=16384`,
  `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_KEEP_ALIVE=30m` (server warm-up keep-alive).
- Harness: `python -m eval.run_grounding --provider ollama --model <tag> --pause 0
  --rate-retries 4 --timeout 900`, `CORPUSMIND_CHAT_TIMEOUT_S=900`.
- Three repetitions of the 80 questions, each as four disjoint shards of 20
  (G-001..G-020, G-021..G-040, G-041..G-060, G-061..G-080), model warmed before each
  repetition. Shard tags `g4_16k_r{1,2,3}`.
- Scorer: the repository scorer (`engine/eval/score.py`) at the commit under test,
  against the frozen gold; merging and structural validation with
  `scripts/validate_user_run.py` from a fresh clone at origin/main (the frozen
  checkout is never moved).
- **Differences by necessity:** the model; `OLLAMA_MAX_LOADED_MODELS=1` (one
  resident model); `CORPUSMIND_OLLAMA_KEEP_ALIVE=30m` on the harness side.
- **Rescue policy — mirrored from the committed qwen arm, replacing the earlier
  "no rescues" draft wording:** a single-question rescue re-run is allowed for a
  record that ended in a transport error (HTTP 502/empty answer), exactly as
  pre-registered for the qwen run: the rescue re-run replaces the errored record in
  the merge only when the original was errored and the re-run is clean; both
  attempts are kept and disclosed; rescues stop per the original rule; NO_ANSWER
  counts as not PASS. (On the qwen arm the rescue recovered availability, not
  correctness — the rescued verdict was HALLUCINATED — so this mirror cannot
  manufacture PASS differences.)

## 4. Outcomes and tests

- **Primary outcome:** per-question majority-vote PASS (PASS in at least 2 of 3
  repetitions), scored by the repository scorer.
- **Pinned comparator:** the committed qwen2.5:7b majority vector
  `benchmarks/results/user-wsl2-7b-16384/analysis/qwen7b_majority_vector.json`,
  sha256 `f36a02ec559e582738420a0e9b90001f83a23d52b54332c09c2769d52d1bb532`
  (as-run verdicts; per-repetition PASS 21/21/23; majority 20/80). The exact McNemar
  pairs on this vector and on nothing else.
- **Primary test:** exact McNemar test (two-sided) on the 80 paired questions, new
  arm against the pinned qwen majority vector. This is the only confirmatory test
  of this plan.
- **Multiplicity:** the declared family of Plan v3 is **extended from four to five
  tests**: {context contrast × Qwen2.5-1.5B, context contrast × Qwen2.5-3B, size
  contrast within Tier A, size contrast within Tier B, **model-family contrast ×
  Tier B (this arm vs qwen2.5:7b)**}. At reporting time, executed tests of the
  extended family are Holm-adjusted jointly over m = 5 (ordered raw p-values
  multiplied by 5, 4, …, monotone enforcement). Two disclosures accompany any
  reported value: (a) the already-published 3b context contrast was adjusted at
  m = 4 (raw 0.00258 → 0.0103, as reported in manuscript v3/v4); re-reporting it
  jointly at m = 5 gives 0.0129 — the conclusion (significant at α = 0.05) is
  unchanged; (b) no post-hoc contrast enters the family.
- **Power / minimum detectable difference, pre-stated:** with 80 paired questions,
  an exact McNemar only reaches p < 0.05 for a landslide among discordant pairs —
  the least-extreme significant splits are 1/9 at m = 10, 2/10 at m = 12, 2/12 at
  m = 14, 3/13 at m = 16, 5/15 at m = 20 (two-sided exact). A non-significant
  result means "no detectable difference at n = 80"; it is **never** evidence of
  equivalence (no TOST is powered here). The arm's principal yield is therefore the
  descriptive comparison below, not the test.
- **Secondary, descriptive only (no tests):** per-repetition PASS counts with
  Wilson 95% CIs; majority-vote PASS with Wilson CI; questions passing in all three
  and in at least one repetition; within-arm pairwise Cohen's κ on binary PASS;
  cross-arm per-repetition agreement and κ (descriptive); five-class verdict
  composition; UNGROUNDED_NUMBER (the scorer's HALLUCINATED) share of attempts;
  NO_ANSWER inventory with error signatures; share of answers with at least one
  tool call; per-category and per-language (English/Arabic) pass counts; latency
  (engine-side elapsed vs wall); tool-call success/failure counts. Claim forms are
  fixed in advance as descriptive ("shifts by X points", "replicates / does not
  replicate"); no significance language attaches to secondaries.
- Repetitions are never pooled into one sample of 240 independent trials.

## 5. Gate before the first full repetition

All of the following must hold for the primary arm:

1. `/api/show` lists the capability `tools`. The digest, quantisation, context
   window and template are recorded in the same session — and `ollama show
   qwen2.5:7b` is recorded in the same session, completing the qwen arm's
   quantisation provenance (manuscript placeholder).
2. Micro-probe through `/v1/chat/completions` (the path the engine uses for tool
   rounds, with no thinking parameter), three requests with a minimal tool schema:
   a tool call is returned in at least 2 of 3 requests, median wall time at most
   45 s, median completion tokens at most 300, and no reasoning text in the message.
3. **Argument-serialization probe:** a single-question harness run of G-076 (the
   malformed-CQL item). The engine must receive a well-formed tool call — the CQL
   parse error is the correct engine response and must be relayed in the answer —
   with zero malformed-argument rejections. Rationale: on the qwen arm every CQL
   failure was an argument-formation error; a chat template that mangles tool-call
   arguments would measure the harness, not the model.
4. **Truncation self-test:** with a throwaway server at `OLLAMA_CONTEXT_LENGTH=2048`
   (port 11435), one long-prompt request produces at least one `truncated = 1`
   slot line — proving the gate's log pattern actually fires on this Ollama build.
   The self-test log segment is archived and committed as gate evidence and is
   excluded from the run's truncation gate (which requires 0 on all *run* segments).
5. A 5-question harness probe (G-001..G-005, `--rate-retries 4`, 900 s deadline):
   at least 4 answered and at least 3 of {G-001, G-002, G-003, G-005} with at least
   one tool call. **G-004 is a capability-gap trap (gold `traps.no_tool`):** a turn
   with no tool call and an explicit unavailability statement is the *correct*
   behaviour there and is not a gate failure.

If 1–3 (or 5) fail, the fallback arm is used and the gate is repeated for it. Probe
outputs are protocol checks, not results; the same questions are run again inside
the full repetitions. The turn-one system prompt is additionally reconstructed with
the arm's tokenizer (offline, the §7.5 analogue) and its token count is written to
`notes.txt` as a descriptive record — the truncation gate, not this count, is the
protocol check.

## 6. Rules

- No rescues beyond the qwen-mirrored rule of Section 3; NO_ANSWER counts as not
  PASS.
- A repetition is re-run only after a protocol violation (host sleep, server crash,
  a second model loaded, wrong server context). Both attempts are kept and
  disclosed; cut-short shard files are renamed `*.FAILED.json`, never deleted.
- Abort rule: if shard 1 of repetition 1 has 10 or more NO_ANSWER records, or fewer
  than 5 questions with a tool call, stop and disclose.
- No change to the engine, gold, scorer or harness during the arm.
- Artifacts are laid out as `benchmarks/results/user-wsl2-gemma4-16384/` (12 shard
  JSONs, per-rep logs, `evidence/`, `rescues/`, `merged/`, `manifest.json`
  regenerated with `benchmarks/scripts/make_manifest.py` at the same commit pin),
  mirroring the qwen arm's folder structure.

## 7. Interpretation limits

Any difference between the arms confounds model family, effective size (~4.5B vs
7.6B), total size, quantisation, chat template, tool-call format and tokenizer
(prompt length). The paper will not attribute a difference to "family". One
machine, one model per family, temperature 0.2 (the engine default). The
per-question deadline-miss set may differ across arms because wall time is
model-dependent (the qwen arm's deterministic 900 s misses G-032/G-077 need not be
misses on a faster arm); miss sets are disclosed per arm and reads that lean on
them are flagged as protocol×speed interactions.

## 8. Manuscript integration checklist (only if the arm is executed)

1. Title unchanged; a new results subsection ("A second model family under the
   same protocol") carries the primary outcome, the composition comparison, and the
   category/language profile.
2. Section 5 of the manuscript already discloses this plan and the extended family
   (v4 sentence); after execution, the joint Holm-at-m = 5 values replace the
   interim ones, with the disclosure note of Section 4.
3. Limitation 3 ("one model family") is rewritten to "two model families, one model
   each, unmatched effective size, one serving stack".
4. The abstract reports the new arm's pass rate **and** its UNGROUNDED_NUMBER share
   in the same sentence.
5. Every number is script-recomputed from committed artifacts; figures come from
   the arm's analysis bundle in the established format.

## Appendix: pinned qwen2.5:7b majority-vote PASS set (20 of 80)

G-001, G-014, G-016, G-017, G-020, G-021, G-022, G-034, G-039, G-040, G-042,
G-045, G-053, G-054, G-055, G-057, G-070, G-071, G-076, G-078.

Full per-question vector (including per-repetition verdicts): the JSON pinned in
Section 4, sha256 `f36a02ec559e582738420a0e9b90001f83a23d52b54332c09c2769d52d1bb532`.
