# AREA AUDIT — do the committed files cover the five benchmarking areas?

**Date:** 2026-11-05 · **Repo state:** `waleedmandour/CorpusMind` (shards at `benchmarks/results/user-wsl2-7b-16384/`, HEAD includes `de70256`)
**Question answered:** the five result areas A1–A5 fixed at the start of this project (Research & Upscaling Report §2, mapping to BENCHMARK_REPORT §1–7). Coverage check per area, against files actually in the repo or in the local analysis bundle — followed by a retest/adjust verdict.

---

## A1 — Grounding fidelity · **COVERED**

| Evidence | Where |
|---|---|
| 7b @16384, 80 q × 3 reps (12 shards, disjoint per rep) | repo `user-wsl2-7b-16384/b7_16k_r{1,2,3}_shard{1..4}.json` |
| 5 rescue records + G-001 retest + 5-question probe | same folder, `rescues/`, `g001_retest.*`, `probe16k*.json` |
| Run logs (authoritative record) | same folder, `logs/*.log` |
| Validator gate: STRUCTURAL: PASS ×3, gold hash `480f5230…` | local `validator_log.txt`; repo `scripts/validate_user_run.py` |
| Merged + repo-scored verdicts, per-question CSV, metrics, figures | local `b7_16k_analysis/` (not yet pushed — pending task) |
| CI comparators: 1.5b/3b @4k freeze triple; pinned 3b @4k control; 1.5b/3b @16384 (n=1) | repo `run-41202610042`, `run-41296669898`, `run-41306198564`, `run-41306208341`, `run-41306203484` |

**Verdict: no retest.** The row is complete, stable (kappa 0.62–0.81), validated.
**Adjust (files, not runs):** (1) upload the still-missing provenance files — `ollama_env.json` (Tier B), `env_qwen2.5-7b.json`, `host_snapshot.txt`, `pip_freeze.txt`, the 3 `ollama_server` log segments; (2) regenerate `MANIFEST.json` over the full folder (currently hashes only the 3 probe-stage files); (3) push the analysis bundle + figures.

## A2 — Segmentation, intrinsic · **COVERED (frozen, deterministic)**

`seg_intrinsic_{PA,NP}.json` + `.meta.json` + `araseg_sha256.txt` in every CI run folder; bit-identical across all 8 freeze runs (PA micro 0.7115 / macro 0.6705; NP micro 0.5572 / macro 0.5469). Deterministic → nothing to retest.
**Optional add-ons never produced:** per-genre F1 breakdown, paired bootstrap on segmentation documents (P2 moves, minutes, offline). Not gating the manuscript.

## A3 — Segmentation extrinsic deltas · **COVERED (frozen); add-on open**

`bench-state/artifacts/f2_pooled_{PA,NP}.json` = the frozen F2 pooled re-run. The P3 "dose-response error-injection curves" move was never run (offline, hours). Recommend: descope to future work or schedule after the draft; it is not a retest.

## A4 — Statistical parity vs references · **COVERED**

`bench-state/artifacts/a6_parity.json` + `engine/eval/parity_stats.py` + `engine/tests/test_language_parity.py`; exact agreement on TTR, Guiraud, G-squared, odds ratio. No retest. Minor docs-only item: pin reference library versions in BENCHMARK_REPORT.

## A5 — Scale and performance · **MOSTLY COVERED; two pre-registered Tier B rows never run**

Covered: `perf_arabic.json` in all freeze runs; `a7-scale/1m|10m` + `f4-scale-zipf` artifacts; between-runner throughput distribution; on Tier B the probe (`probe16k.json`, ~171 s/q) and full-row per-question latency (`metrics.json: latency_s`, median ≈172 s, question-difficulty correlation r = 0.61–0.74).

**Open (pre-registered in Plan v3 §3/§5, never run):**
1. **Tier B bridging run** — 1.5b + 3b @16384 on the user machine (n≈3.5–4.5 h at n=1, ≈11–13 h at n=3; estimates from the measured 171 s/q).
2. **Mandatory synthetic 250k long-context row on Tier B** (n=1 ≈ 4–5 h).
3. Fresh pinned **1.5b @4k control** (n=1 ≈ 1–1.5 h) — only 3b got a fresh control.

---

## Consequence for the pre-registered statistics family (Plan v3 §7)

Family = {context contrast × model} ∪ {size contrast × platform}, exact McNemar on collapsed paired verdicts + Holm.

| Contrast | Computable today? |
|---|---|
| 3b context (pinned 4k control n=1 vs 3b @16384 n=1) | **YES — paired per-question, McNemar + Holm, offline, minutes; not yet computed** |
| 1.5b context | NO — only the freeze 4k triple exists (Ollama-version confound); needs open item A5.3 or the claim is dropped |
| Size contrast within platform | NO — needs bridging run (A5.1) |
| 7b row | No comparator exists; reported descriptively (Wilson CIs + kappa already in `metrics.json`) |

Scorer second-judge agreement: **done** (independent re-score + kappa, in `metrics.json`). Derived-number audit: **subsumed** — the repo scorer's HALLUCINATED class is the derived-number check.

## Bottom line

- **Retest: none required.** The 7b × 3-rep row and all frozen CI rows stand.
- **Adjust (no machine time):** compute McNemar + Holm for the 3b context contrast; push the analysis bundle, provenance files; regenerate MANIFEST.
- **Decide before drafting (machine time, optional):** bridges (A5.1) buy the within-platform size claim; 250k synthetic row (A5.2) can be descoped with a one-sentence justification (prompt window fixed at 16384 — corpus-size effect is confounded by the fixed window on this harness); 1.5b 4k control (A5.3) only if the 1.5b context contrast is worth claiming.
- Everything else in A1–A5 is publishable from the files as they stand.
