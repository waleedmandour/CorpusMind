# Addendum 1 to the pre-specified gemma4 E4B arm plan (plan v1)

**Status: written before any measurement of this arm.** The commit timestamp of this
file on `github.com/waleedmandour/CorpusMind` is the record of when this addendum was
fixed. It amends `2026-11-06_gemma4-e4b-arm-plan-v1.md` in exactly two places: the
model tag (§A1) and the availability rule (§A2). Everything else in plan v1 —
protocol, gate, outcomes, tests, multiplicity, rescue and abort rules, artifact
layout, interpretation limits — is unchanged and remains binding.

## A1. Tag correction

Plan v1 §2 names the primary arm `gemma4:e4b-it-q4_K_M`. Checked against the Ollama
library on 6 November 2026: `gemma4` is published, but no `-it` or `-q4_K_M` suffixed
E4B tag exists. The served tags include `gemma4:e4b` (E4B efficient variant, 4.5B
effective / ~8B total with embeddings, 128k context, text+image, native function
calling) — the model plan v1 actually described. Ollama serves the E-series
pre-quantised; quantisation is not part of the tag.

**The primary arm's tag is corrected to `gemma4:e4b`.** No other consequence: plan v1
§2/§5 already require recording the exact digest, quantisation level, parameter size,
context window and capability list from `/api/show` (and `ollama ls`) *before* the
first measurement, so no pre-specification of the serving configuration is lost. The
motivation paragraph of plan v1 §2 (E4B class ≈ the 16 GB CPU serving footprint;
~4.5B effective vs 7.6B; size unmatched and disclosed) applies verbatim to this tag.

## A2. Availability rule (decided before the first shard, not after a failure)

1. Run `ollama pull gemma4:e4b` on the run machine (Ollama 0.40.13, no upgrade).
2. **If the pull succeeds**, proceed to the plan v1 §5 gate for `gemma4:e4b`.
3. **If the pull fails** — "manifest not found" / "model not found", or a message
   indicating the build cannot serve the architecture (e.g. requires a newer Ollama) —
   capture the exact command and the complete error output to
   `benchmarks/results/user-wsl2-gemma4-16384/evidence/pull_failure.txt`. This file is
   committed as protocol evidence even though the arm never runs.
4. **Ollama is not upgraded.** The 0.40.13 pin is part of the frozen protocol shared
   with the committed qwen2.5:7b comparator; upgrading the serving stack for one arm
   would confound the model-family contrast with a server-version change. If a Gemma
   arm is still wanted, it requires a new pre-specified plan (new file, new commit)
   that declares the serving-stack deviation explicitly; it does not revive this one.
5. **Consequence of a failed pull:** the plan v1 §5 pre-run gate cannot pass for the
   primary arm, so the **pre-specified fallback arm `llama3.1:8b`** (plan v1 §2) is
   activated. The §5 gate is repeated in full for the fallback; exactly one arm runs
   in full; the arm choice is written to `notes.txt` before the first repetition.
6. Fallback-arm naming (by necessity, disclosed): artifacts under
   `benchmarks/results/user-wsl2-llama3.1-8b-16384/` (mirroring the qwen arm's
   layout), shard tags `l8_16k_r1..r3` (mirroring `b7_16k_r1..r3`), evidence files
   `env_llama3.1-8b.json`. The single confirmatory test remains the exact McNemar of
   plan v1 §4 on the pinned qwen majority vector; the declared family stays extended
   from four to five tests, now realised as {llama3.1:8b vs qwen2.5:7b}. The §7
   interpretation limits apply verbatim (family, quantisation, chat template,
   tokenizer confounded; llama3.1:8b at 8.0B total is closer to 7.6B in total size
   than E4B's ~8B-with-embeddings/4.5B-effective — the paper says so either way).
