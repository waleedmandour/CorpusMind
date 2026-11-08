# Addendum 2 to the pre-specified gemma4 E4B arm plan (plan v1)

**Status: written before any measurement of this arm — no full-repetition data exists
(0/12 shard files).** The commit timestamp of this file on
`github.com/waleedmandour/CorpusMind` is the record of when this addendum was fixed.
It amends `2026-11-06_gemma4-e4b-arm-plan-v1.md` in exactly one substantive place (the
§5 item 4 log marker, §A3 below) and documents the §5 fallback activation for the
primary arm (§A4). Everything else in plan v1 and addendum 1 — protocol, gates,
outcomes, tests, multiplicity, rescue and abort rules, artifact layout, interpretation
limits — is unchanged and remains binding.

## A3. Truncation self-test marker (amends §5 item 4)

On the pinned serving stack (Ollama 0.40.13 — the build addendum 1 §A2.4 freezes as
part of the shared protocol), the §5 item 4 self-test run on 8 November 2026 produced:

- `truncated = 1` : 0 lines
- `truncating input prompt` : 1 line
- `prompt_eval_count=1027` for an ~8k-token request into `OLLAMA_CONTEXT_LENGTH=2048`

Truncation occurred and is log-detectable, but this build's runner emits the
`truncating input prompt` marker, not the `truncated = 1` slot line plan v1 §5 item 4
expected. The marker is a property of the Ollama build, not of the model; as plan v1
is written, no arm — including the fallback — can pass item 4 on the pinned build.

**Amendment: §5 item 4 passes when the self-test log contains at least one line
matching EITHER `truncated = 1` OR `truncating input prompt`, with the long-prompt
request itself succeeding.** The run-time truncation gate is unchanged and remains
stricter: both patterns must stay at 0 on all run segments (this is already how the
runbook's truncation counter is computed). The self-test log segment is archived and
committed as gate evidence exactly as §5 item 4 requires.

## A4. Gate 2 failure of the primary arm → fallback activation

On 8 November 2026 the §5 item 2 micro-probe for `gemma4:e4b` returned, on the exact
condition the item specifies (`/v1/chat/completions`, the engine's tool-round path,
no thinking parameter):

- tool call returned: 3/3 (need ≥ 2/3) — pass
- median wall time: 34.5 s (need ≤ 45 s) — pass
- median completion tokens: 188 (need ≤ 300) — pass
- **no reasoning text: FAIL — reasoning text present in 3/3 messages (544 / 1058 /
  384 chars)**

Root cause, verified in the frozen engine source (v2.0.2, commit
`5a5e43fa0c9e6a903dc06f79579b732a9f666bca`): the engine's native `/api/chat` payload
pins `"think": false` for all models, but the OpenAI-compatible tool-round path
(`/v1/chat/completions`) sends no thinking-control field, and the engine's
`reasoning_effort` option is implemented for the cloud provider only. Under the
pre-specified condition the model therefore defaults to thinking on every tool round.
The probe's diagnostic requests (`reasoning_effort=none`) confirm the behaviour is
switchable at the API level (0 reasoning chars, 3/3 tool calls), but the frozen
checkout cannot pin it, and modifying the engine would break the shared-commit
guarantee with the committed qwen2.5:7b comparator (§A2.4 of addendum 1).

**Consequence (plan v1 §5: "If 1–3 (or 5) fail, the fallback arm is used and the gate
is repeated for it"):** the pre-specified fallback arm `llama3.1:8b` (addendum 1
§A2.5–A2.6) is activated. The §5 gate is repeated in full for the fallback; exactly
one arm runs in full; the arm choice is written to `notes.txt` before the first
repetition. The primary arm is terminated at the gate stage with zero measurement
data (0/12 shard files); all of its gate artifacts are retained in place
(`~/cm_runs/gemma4/`, `engine/eval/runs/g4_16k_*`) and committed with the run's
evidence. The confirmatory-test family stands as re-declared in addendum 1 §A2.6:
realised as {llama3.1:8b vs qwen2.5:7b}, five tests, no further change.
