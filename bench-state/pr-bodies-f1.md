# Pre-written PR bodies (F1) — open these after pushing the local branches

Push commands (fast-forward only, no force):
    git push origin bench/local-results bench/extra-1 bench/scale-1 bench/t6-report bench/state
PR base for all: main @ ee42bfa (t6-report PR already exists as #57 — push
adds commits to it, do not open a new one).

---

## PR A — bench/local-results (NEW, ce77f49)

Title: bench: raw run envelopes for every local grounding run (1.5b×3, 3b×3, 7b probe)

Body:
Adds raw `paper_run.json` / `paper_report.json` under `benchmarks/results/`
for every local (Ollama) run of the A3 protocol, verbatim from the run
snapshot branches / bench-state archive (see README-local-runs.md):

- qwen2.5:1.5b ×3 — 41173022988, 41185282664, 41189716613
- qwen2.5:3b ×3 — 41176056150, 41194918539, 41202610042
- qwen2.5:7b timing probe — 41206910830 (labeled probe, not an A3 member)

Disclosed: paper_run.json for 3b #2/#3 is not archived anywhere reachable
(snapshot-branch race; reports only). Data-only —
`git diff ee42bfa -- engine ':!engine/eval'` is empty.

## PR B — bench/extra-1 (NEW, 76454a0)

Title: eval: pooled segmentation-downstream re-run (F2) + parity battery hardening (F3)

Body:
- segmentation_downstream.py: `--pool` mode (one engine vs one gold corpus
  per condition), realistic thresholds, data-driven two-token CQL patterns;
  fixes the response-key bug (`rows` vs `top_collocates`/`top_ngrams`) that
  recorded the frozen artifacts' colloc/ngram zeros, and dict-or-list
  ingest handling.
- parity_stats.py: NOT_TESTED semantics for empty comparisons; synthetic
  10k/50k/100k texts; 876-table 2×2 battery incl. zero cells; odds-ratio
  reference corrected to Table2x2(shift_zeros=False) — the statsmodels
  default silently applies the Haldane correction; undefined-OR tables
  excluded, not scored; STTR residual disclosed as LR's unconditional
  last-segment discard.
- 7b runbook + sign-convention docs already on this branch (697458c).
Raw outputs archived on bench/state: f2_pooled_{PA,NP}.json, a6_parity.json.
Gate: `git diff ee42bfa -- engine ':!engine/eval'` is empty.

## PR C — bench/scale-1 (NEW, 3ffedaf)

Title: scale: --corpus-mode zipf (200k+ types) + repetitive-text labeling (F4)

Body:
Adds the F4 re-run mode (deterministic PCG64 seed 20261031, zipf(a=1.15),
vocab 220,000, ~20-token sentences; KWIC query words zw1/zw2) and makes the
default mode self-label its output REPETITIVE SYNTHETIC TEXT (the
2026-10-31 A7 runs 41202459225/41203959363 used it). Local 100k validation:
27,322 types, degraded=false, keyness 100+100. Follow-up dispatch needed:
`--sizes 1000000,10000000 --corpus-mode zipf` (see STATE.md §11). Gate: empty.

## PR D — update to #57 (bench/t6-report, a0b3283)

Push-only; PR #57 gains the F5/F2/F3/F4 corrections (pooled extrinsic with
the "robust to segmentation" claim deleted, per-category grounding,
parity battery corrections, REPETITIVE SYNTHETIC TEXT labels, plan §1
segmenter wording fixed to "on par on PA (67.05 vs spaCy 67.29), above on NP").

## Merge order (proposal; maintainer decides, nothing merged by the bot)

1. #50, #51 (data snapshots: seg canonical, A4 222-doc)
2. #52, #53, #54, #55, #56 (local-row snapshots 1.5b×3, 3b×1, 3b×2)
3. NEW: snapshot PR for bench/snapshot-run-41202610042 (3b #3 — never opened)
4. NEW: PR A (bench/local-results) — raw envelopes
5. NEW: PR B (bench/extra-1) — eval tooling
6. NEW: PR C (bench/scale-1) — scale tooling
7. #57 LAST (report) so it lands with its artifacts and tooling
