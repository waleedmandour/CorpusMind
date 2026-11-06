# Pre-registered context contrast — qwen2.5:3b, pinned 4k control vs 16384

**Added 2026-11-05 · Companion machine-readable artifact: `stats_3b_context_contrast.json`**
**Pre-registration:** CorpusMind Benchmark Re-run Plan v3 §7 — unit of analysis is the
question; n=1 arms collapse to the single verdict; primary test is **exact McNemar** on
the collapsed paired verdicts; **Holm** across the declared family.

## Arms (both scored by the repo scorer, same frozen gold — gold meta blocks identical)

| Arm | Run | Ollama | Context | Model digest source | PASS / 80 | Wilson 95% CI |
|---|---|---|---|---|---|---|
| Control (default ctx) | `run-41306198564` | 0.40.13 (pinned) | build default 4k (`OLLAMA_CONTEXT_LENGTH_env: null`) | recorded in `ollama_env.json` | **4 (5.0%)** | [2.0, 12.2] |
| Arm (16384) | `run-41306203484` | 0.40.13 (pinned) | 16384 | recorded in `ollama_env.json` | **18 (22.5%)** | [14.7, 32.8] |

Both manifests record workflow plumbing commits (`110e6c4c`, `ef983d69`); the engine
measurement code is the frozen v2.0.2 grounding stack, and each run ships its own
`ollama_env.json`, so the pair differs by context length only.

## Paired table (80 questions, binary PASS vs not-PASS)

| | 16k not-PASS | 16k PASS | total |
|---|---|---|---|
| **4k PASS** | 3 (b) | 1 | 4 |
| **4k not-PASS** | 59 | 17 (c) | 76 |
| total | 62 | 18 | 80 |

- **b = 3** — PASS at 4k only: G-013, G-016, G-075
- **c = 17** — PASS at 16384 only: G-001, G-002, G-007, G-011, G-014, G-021, G-033,
  G-037, G-043, G-051, G-053, G-054, G-055, G-069, G-070, G-071, G-076

## Exact McNemar (two-sided)

p = 2 · P(X ≤ 3), X ~ Binomial(20, 0.5) = **0.00258** (raw)
Holm-adjusted over the **declared four-test family** {ctx×1.5b, ctx×3b, size×CI,
size×TierB} = **0.0103** (convention: the raw p is multiplied by the declared family
size, 4 — the same convention as the manuscript, which reports 0.010). The companion
`stats_3b_context_contrast.json` records both values as of 2026-11-06; its original
`p_two_sided_holm_adjusted` = 0.00258 reflected the executed-tests-only reading (one
executed test, identity adjustment), which is *not* the citable convention here.

**Family disclosure (not imputed, simply not run):** ctx×1.5b has no clean comparator
(only the freeze-version 4k triple exists — Ollama-version confound; see AREA_AUDIT.md);
both size contrasts require the Tier B bridging runs, descoped 2026-11-05.

**Result: the 16384 arm improves 3b grounding (p ≈ 0.0026), significant after Holm.**

## Verdict-level reading (descriptive, same 80 pairs)

| 4k ↓ \ 16k → | PASS | HALLUCINATED | MISSING_NUMBER | TRAP_FAILURE |
|---|---|---|---|---|
| **PASS** | 1 | 2 | 0 | 1 |
| **HALLUCINATED** | 6 | 17 | 6 | 0 |
| **MISSING_NUMBER** | 9 | 12 | 11 | 1 |
| **TRAP_FAILURE** | 2 | 0 | 1 | 11 |

- Five-class exact agreement 40/80 (50.0%); binary agreement 60/80 (75.0%).
- 9 questions move MISSING_NUMBER → PASS: with the full prompt in window the model
  quotes the gold numbers instead of omitting them.
- 12 move MISSING_NUMBER → HALLUCINATED: numbers now get quoted but are wrong — the
  failure mass shifts from *missing* to *hallucinated*, the same signature the 7b
  Tier-B row shows, now demonstrated within one model across context lengths.
- Traps are context-stable: 11 of 14 TRAP_FAILURE stay TRAP_FAILURE.

## Caveats (disclosed, per plan §10 wording rules)

1. n=1 per arm: the contrast is computed exactly as pre-registered for the n=1
   collapse (single verdict per question), but no rep-to-rep variance is modeled on
   the CI side. The Tier-B 7b row (n=3) is not part of this contrast.
2. Scope: this tool's prompt template and the Qwen2.5 family as served by Ollama
   0.40.13 at these two context lengths — not LLM grounding in general.
3. Both arms ran under CI's 300 s per-question deadline (unlike the Tier-B 900 s).
