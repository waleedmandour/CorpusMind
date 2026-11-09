# Addendum 2 to the pre-specified gemma4 E4B arm plan (plan v1) — post-run disclosures

**Status: written after the arm completed, as the disclosure document the run
ledger references.** Unlike addendum 1 (fixed before any measurement), this
addendum records four events that arose during the arm's execution and one
post-run bookkeeping step. It amends nothing in plan v1 or addendum 1; every
section below *reports* under the rules those documents already fixed. The
ledger lines quoted here are committed verbatim in
`benchmarks/results/user-wsl2-llama3.1-8b-16384/evidence/notes.txt` (llama arm)
and `benchmarks/results/user-wsl2-gemma4-16384/evidence/notes.txt` (primary arm).

## A3. Gate-4 truncation self-test: log-pattern amendment (both arms)

Plan v1 §5.4 requires the 2048-context self-test to produce "at least one
`truncated = 1` slot line", proving the gate's detection pattern fires on the
pinned Ollama build. On Ollama 0.40.13 the slot line does not carry that marker
string; the equivalent, stricter server-log line is **`truncating input prompt`**
(with the prompt token count on the same line). Both arms' gate 4 therefore ran
with the substituted pattern:

- gemma4:e4b (2026-11-08T10:52–11:10Z diagnostics): `truncated = 1` lines 0;
  `truncating-input-prompt` lines **1** (prompt_eval_count 1027) — "detection
  proven … Amendment required".
- llama3.1:8b (2026-11-08T16:06:12Z, gate 4 PASS): `truncated = 1` lines 0;
  `truncating-input-prompt` lines **1** — recorded in the ledger as
  "(addendum-2 A3)".

**Amendment:** for this arm the plan's §5.4 marker is read as the
`truncating input prompt` line, and the run gate is *stricter* than plan v1's
wording: it requires **zero matches on both patterns** across all run server
segments. The llama run gate result: 0 and 0
(`evidence/truncation_gate.txt`); the self-test log is excluded from the run
gate exactly as §5.4 pre-specifies. No other gate semantics change.

## A4. Primary arm terminated at gate 2; fallback activated; committed gate-evidence pack

Per plan v1 §2 and addendum-1 §A2, the fallback activates only on a failed
pre-run gate. That is what happened, and it happened **before any measurement**:

- `gemma4:e4b` was pulled successfully (5.5 GB, `pull_raw.txt`) and gate 1
  passed (tools capability present; digest/quantisation/context/template
  recorded). Gate 2 (micro-probe through `/v1/chat/completions`, §5.2) failed
  **repeatedly across four sessions** (2026-11-07T16:57Z → 2026-11-08T11:06Z,
  `probe0 rc=4`).
- Diagnosis (ledger OBSERVATION, 2026-11-08T11:21Z): gemma4:e4b **defaults to
  thinking on the engine tool-call path**; the `/v1` compat payload the frozen
  engine sends carries no thinking control (`CORPUSMIND_CLOUD_REASONING_EFFORT`
  is cloud-only), so reasoning text appears 3/3 on the pinned no-thinking
  tool-round path — an unfixable §5.2 violation in frozen checkout `5a5e43fa`.
- DECLARATION (2026-11-08T16:00:52Z, quoted in the run ledger): "primary arm
  gemma4:e4b terminated at gate stage (gate 2 FAIL — reasoning text 3/3 on the
  pinned no-thinking tool-round path; frozen engine sends no thinking control on
  /v1 compat). Zero measurement data (0/12 shards). Fallback arm llama3.1:8b
  activated; gate repeated in full. Artifacts retained in place."
- The fallback's own gates 1–5 all PASSED on 2026-11-08 (16:04–16:28Z), and the
  arm choice was written to `notes.txt` at 17:24:56Z — **before the first full
  repetition**, as §A2.5 requires.
- The primary arm's evidence pack is committed unchanged at
  `benchmarks/results/user-wsl2-gemma4-16384/` (gates, probe attempts incl.
  `*.attempt-*.json`, truncation self-test logs, pull record, plan
  sha256/commit pins). Its `merged/` folder contains only the 5-question gate
  probe — no bank measurement exists for gemma4:e4b. The pack also completes
  plan v1 §5.1's side-requirement: `ollama show qwen2.5:7b` was recorded in the
  same session (`evidence/qwen_meta/`), filling the qwen arm's quantisation
  provenance.
- **Post-run incident disclosure.** One runbook invocation outside tmux on
  9 November 2026 omitted the arm env prefix (`MODEL=llama3.1:8b
  SLUG=llama3.1-8b TAG=l8_16k`) and therefore executed against the runbook's
  default gemma4 path. It produced no llama-tagged artifact and changed no
  committed llama-run file (every llama artifact carries the `l8_16k` tag; the
  bundle's manifest hashes of pre-existing files are unchanged). All subsequent
  runbook calls carried the explicit env prefix. The gemma4-side outputs of the
  incident are retained inside the committed evidence pack above.

## A5. G-059 transport failures and rescue outcomes (plan v1 §3 rescue policy)

G-059 (register-share question; the slowest item under CPU-only inference)
ended in HTTP 502 ReadTimeout in reps 1 and 3 (walls 1273.7 s / 1312.5 s); rep 2
answered it in 593.3 s. One rescue per errored record, per the pre-registered
policy (mirrored from the qwen arm):

- **rep 1 rescue FAILED** (2026-11-09T09:25–09:49Z): all 4 rate-retries
  exhausted on ReadTimeout → HTTP 502, empty answer, wall 1385.4 s
  (`rescues/l8_16k_r1_rescue_G-059.json`). Not retried further, per the rule.
- **rep 3 rescue SUCCEEDED** (2026-11-09T09:49–10:10Z) on the 4th rate-retry:
  clean re-run with tools `[get_corpus_overview, get_frequency]`, wall 1210.8 s
  (`rescues/l8_16k_r3_rescue_G-059.json`).

Under plan v1 §3 the clean rep-3 re-run "replaces the errored record in the
merge". The committed validator pipeline merges shards only — rescue records
live in `rescues/` and are never folded into `merged/` — so, mirroring the 7b
arm's `b7_16k_r2_rescue_applied` convention, the as-registered reading is
committed separately as `merged/l8_16k_r3_rescue_applied.scored.json`:

- the repo scorer marks the rescued answer **HALLUCINATED** (it quotes 11 /
  4.721% — tool numbers for a frequency question whose gold expects the
  register shares 0.75 / 0.25 / 0.0);
- rep-3 PASS count **unchanged** (19); only NO_ANSWER drops 1 → 0
  (HALLUCINATED 24 → 25);
- the majority vector, the confirmatory McNemar, and every other reported
  number are identical under the as-run and rescue-applied readings, because
  G-059 is not-PASS either way. The as-run NO_ANSWER remains the verdict of
  record in `merged/l8_16k_r3_merged.scored.json`.

Both original records and both rescue attempts are kept; no timeout was
edited; no attempt file was deleted (ledger §"G-059 transport disclosure").

## A6. Analysis bundle and manifest regeneration

The arm's analysis bundle now lives at
`benchmarks/results/user-wsl2-llama3.1-8b-16384/analysis/` in the established
7b-arm format (`RESULTS_SUMMARY.md`, `metrics.json`, `per_question.csv`,
`llama31_majority_vector.json`, `stats_confirmatory_mcnemar.json`,
`stats_descriptive_ci_contrasts.json`, `scorer_diff.json`,
`corpus_totals_hallucination.json`, `g059_no_tool_inventory.json`,
`FIGURE_CAPTIONS.md`, `figures/`). Because the folder grew, `manifest.json` was
regenerated over the full bundle (lowercase, commit-under-test `5a5e43fa…`,
run-url `local://Waleed-Desktop/WSL2-Ubuntu24.04-tierB-user-run`), superseding
the 52-file pre-analysis index — the same step the 7b arm recorded in its
RESULTS_SUMMARY §8. Per-file hashes of pre-existing artifacts are unchanged;
only the file *set* and the manifest itself differ.
