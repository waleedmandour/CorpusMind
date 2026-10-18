# CorpusMind — System Figures (Manuscript Figure Set, updated 2026-10-18)

Six original figures for the Journal of Computational Linguistics
submission (20-page paper). Okabe-Ito colorblind-safe palette, English
labels, conceptual-clean naming (real technologies, no file paths).

File numbers reflect creation order, not the paper's figure numbers —
number figures in the manuscript by order of appearance (fig0, written
for Section 3, comes before fig1 of Section 4).

## Files

| Figure | Content |
|---|---|
| `fig0_design_principles` | The nine non-negotiable design principles grouped into three families — Data sovereignty & ethics (P1 local-first, P9 biometric restraint), Epistemic discipline (P2 grounded AI, P3 effect size + significance, P5 framework-lensed hypotheses), Verifiable honesty (P4 transparency, P7 honest scale, P8 reproducibility) — plus P6 Arabic-first-class as the cross-cutting principle. Each card names the shipped mechanism that enforces it (hard-disable switch, 27-tool agent, six association tests + four effect sizes, twelve framework templates, annotation versioning…). |
| `fig1_system_architecture` | Three-tier architecture: Presentation (Tauri 2 shell + React/TS web UI, Sigma.js, RTL) → Analysis engine (FastAPI sidecar, SQLite, background jobs, Smart Troubleshooting) → NLP & AI layer (spaCy ×5, CAMeL Tools, bge-m3 vectors, grounded AI agent). Student Mode sidecar shown as an optional dashed column. |
| `fig2_analysis_workflow` | End-to-end researcher workflow in four phases: corpus construction → quantitative analysis → interpretation & grounding → publication outputs (incl. methods.pdf and YAML provenance). |
| `fig3_arabic_pipeline` | Arabic NLP pipeline: input (pasted text or pre-loaded 'Your Corpus' corpus) → normalization → CAMeL morphology → variety identification → analysis surfaces → aggregated report & exports. Semantic color: gray input / blue processing / teal output. |
| `fig4_grounded_ai_loop` | The grounded-AI contract loop: query → planner (27 tools) → deterministic tool execution → evidence candidates → grounding verification → answer (grounded with citation / unsupported flagged), with the dashed re-query loop and the provenance note. |
| `fig5_classroom_deployment` | Student Mode deployment: teacher device (engine + Caddy classroom server + local LM + anonymous audit log) ↔ student browsers over classroom LAN, with the isolation rule. |

## Formats per figure

- **`.pdf`** — vector, single page, exact figure aspect. Preferred for
  LaTeX: `\includegraphics[width=\textwidth]{fig1_system_architecture.pdf}`
- **`.svg`** — editable vector (text stays text; opens in Inkscape /
  Illustrator). `fig4`'s arrows are real SVG paths; all labels are
  selectable text elements.
- **`.png`** — ~600 dpi raster (5.8 in wide for fig1) for Word documents
  and review portals.

No internal figure titles are baked in — add captions in the manuscript
(e.g. "Figure 1: CorpusMind system architecture.").

## Regenerating

The figure sources (HTML bodies plus a small Playwright-based renderer
that outputs PNG, vector PDF, and text-editable SVG) are maintained in
the development workspace. Rendering requires Python with Playwright and
a Chromium build; edit the figure bodies or the shared design-token
renderer and re-run the two-step generation. The renderer warns on any
wrapped-text/hyphen anomaly that would desynchronize the SVG export from
the browser rendering.

## Design tokens

Okabe-Ito: blue `#0072B2`, teal `#009E73`, orange `#E69F00`, vermillion
`#D55E00`, sky `#56B4E9`, purple `#CC79A7`, gray `#64748B` — saturated
hues on borders/accents only; fills are their pale tints. Canvas white,
connectors `#94A3B8`, text `#1F2937`.
