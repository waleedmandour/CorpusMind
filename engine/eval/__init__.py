"""CorpusMind evaluation harness (grounding + segmentation).

This package is NOT imported by the engine runtime. It provides:

1. The assistant grounding-fidelity harness (``build_gold`` / ``run_grounding``
   / ``score``): a fixed bilingual snapshot corpus, a bank of ~80 questions,
   frozen tool-output gold, and a scorer that classifies every number an
   assistant quotes as grounded, wrong, or hallucinated.
2. The Arabic sentence-segmentation evaluation against the public AraSEG
   corpus (Elkholy et al., EMNLP Findings 2026): intrinsic boundary P/R/F1
   plus downstream consumer deltas (KWIC, collocations, n-grams, CQL scope,
   sentiment, learner CAF, Gale-Church alignment).

Discipline (inherited from the measures_v2 golden suite): gold values are
frozen ONCE from the running engine, cross-checked at build time against
independent recomputation where the semantics are unambiguous, and never
regenerated silently from the code under test. A code-vs-gold disagreement
is a stop-and-investigate signal, not a regeneration trigger.
"""

__version__ = "1.0.0"
