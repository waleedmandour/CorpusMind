# Figure captions — llama3.1:8b @16384 analysis bundle (manuscript-ready)

All figures are generated from `metrics.json` / `per_question.csv` in this folder,
which are computed from the committed as-run artifacts (repo-scorer verdicts of
record, frozen gold `480f5230…`). PNG (150 dpi) and PDF versions are provided.
Captions are written for direct reuse in the LRE manuscript.

**Figure 1.** Verdict composition per repetition (`fig1_verdict_composition`).
Five-class composition of the 80 grounding questions in each of the three
repetitions of the llama3.1:8b @16384 arm (repo scorer, as-run). PASS 18/21/19;
MISSING_NUMBER 25/22/22; HALLUCINATED 23/26/24; TRAP_FAILURE 13/11/14;
NO_ANSWER 1/0/1 (the single G-059 transport error).

**Figure 2.** PASS rates with Wilson 95% CIs (`fig2_pass_rate`). Per-repetition
PASS rates 22.5% / 26.2% / 23.7% and the majority-vote rate (PASS in ≥2 of 3)
23.8%, all on n = 80 paired questions.

**Figure 3.** Per-question verdict map across repetitions
(`fig3_verdict_heatmap`). Each row is one of the 80 questions, columns are
repetitions; colour gives the five-class verdict. Reading aid for stability:
15 questions are PASS in all three repetitions; 56 are never PASS.

**Figure 4.** Per-category PASS rates (`fig4_category_pass`). Stable strengths
(sentiment 5/5 in every rep; dispersion 4–6/7; discourse 2/3) against stable
zeros (diversity 0/7, collocation 0/6, register 0/5, arabic_tools 0/4), with
keyness, kwic, cql and corpus_stats unstable across reps.

**Figure 5.** Per-question wall time, answered questions only
(`fig5_latency`). Medians 199.0 / 191.3 / 201.8 s; the two G-059 transport
errors (1273.7 s, 1312.5 s) are excluded as NO_ANSWER and annotated. CPU-only
serving (Ryzen 5 4500U) at the pinned Ollama 0.40.13 / 16384 context.

**Figure 6.** Repetition stability (`fig6_reproducibility`). Five-class
identical-verdict rates 73.8% / 68.8% / 77.5%; binary PASS agreement
93.8% / 91.3% / 92.5%; Cohen's κ (binary) 0.83 / 0.75 / 0.80 for rep pairs
r1–r2 / r1–r3 / r2–r3.

**Figure 7.** PASS rate across arms, descriptive (`fig7_arm_comparison`). The
three llama3.1:8b @16k repetitions and their majority (19/80) against the
pinned qwen2.5:7b @16k majority (20/80) and the three CI arms (qwen2.5:3b @4k
4/80; qwen2.5:3b @16k 18/80; qwen2.5:1.5b @16k 15/80; n=1 each, 300 s CI
deadline). No significance language attaches to the non-pinned pairs; the
confirmatory comparison is Figure 2 / `stats_confirmatory_mcnemar.json`.
