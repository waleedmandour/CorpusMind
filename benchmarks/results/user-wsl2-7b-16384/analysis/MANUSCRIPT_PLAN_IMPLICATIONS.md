# Manuscript plan implications - after provenance completion (2026-11-05)

**Bottom line: the drafting plan stands.** The core contribution (7b@16384
grounding fidelity, three-rep stability, CPU-only feasibility on commodity
hardware) is unchanged and is now backed by a complete, verifiable artifact
chain. Four targeted upgrades are recommended before drafting; no structural
overhaul is needed.

## 1. Headline claims (unchanged, now fully supported)

- Pooled PASS 27.1% (65/240, Wilson 95% CI [21.9, 33.0]); per-rep 26.2 / 26.2 / 28.7%.
- Stability: Cohen's kappa 0.62-0.81 (PASS binary), exact verdict agreement
  76.2-82.5%, 16-question stable PASS core.
- Feasibility: CPU-only WSL2, median ~172 s, p95 <= 305 s against the 900 s
  deadline; all 240 attempts accounted for (9 disclosed HTTP 502 misses,
  1 successful rescue, 4 protocol-stopped failed rescues).
- Provenance (new): `evidence/` complete (Ollama 0.40.13 pin, ctx 16384, host
  snapshot, pip freeze, three server-log segments with truncation gate = 0),
  full-folder `manifest.json`, STRUCTURAL: PASS validator gate, deterministic
  repo-scorer re-scoring.

## 2. Upgrade A - promote the pre-registered context contrast to its own subsection

The executed contrast (3b: pinned 4k control `run-41306198564` vs 16384
`run-41306203484`) is the paper's only causal result: exact McNemar
p = 0.00258 raw, Holm-adjusted over the declared four-test family = 0.0103,
22.5% vs 5.0% PASS. Give it a dedicated results subsection with a methods
paragraph (exact McNemar, declared Holm family, unexecuted contrasts
disclosed), the paired 2x2 and joint-verdict tables from
`MCNEMAR_3b_CONTEXT_CONTRAST.md`, and promote fig7 to a central figure.
State the scope honestly: this prompt template, Qwen on Ollama 0.40.13,
n=1 per arm, CI 300 s deadline.

## 3. Upgrade B - name the failure-mode shift as a finding

Longer context converts omissions into fabrications: in the paired 3b table,
9 questions move MISSING_NUMBER -> PASS and 12 move MISSING_NUMBER ->
HALLUCINATED; at 7b@16k HALLUCINATED is the dominant class (31-35 of 80 per
rep). Framing for the discussion: context window size moves the *failure
mass*, not just the pass rate - grounding-fidelity evaluation should report
verdict composition, not only PASS rates. This is a distinctive, quotable
contribution for LRE.

## 4. Upgrade C - provenance & reproducibility section

One compact section citing the full chain: frozen gold (480f5230...), frozen
engine 5a5e43fa (v2.0.2 tag), `evidence/` chain + full-folder `manifest.json`
+ validator STRUCTURAL gate + independent re-score cross-check. Reproduction
is a single validator command (RESULTS_SUMMARY §9). No new experiments needed.

## 5. Scope guards (unchanged, per AREA_AUDIT.md)

- No 1.5b context contrast and no corpus-size claims: unexecuted, disclosed.
- 4k rows carry the F7 prompt-truncation confound; CI arms run a 300 s
  deadline vs the user run's 900 s.
- Single prompt template, single model family; five-class verdicts are
  repo-scorer semantics (independent re-score differences disclosed, not fatal).

## Figure mapping (captions in FIGURE_CAPTIONS.md)

| figure | content | manuscript role |
|---|---|---|
| fig1 | verdict composition | results |
| fig2 | PASS rate | headline |
| fig3 | verdict heatmap | stability |
| fig4 | category pass rates | error profile |
| fig5 | latency | feasibility |
| fig6 | reproducibility | cross-checks |
| fig7 | arm comparison | context contrast (promoted) |

Page budget: unchanged (18-25 pp); Upgrades A-C replace weaker descriptive
text rather than adding length.
