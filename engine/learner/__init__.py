"""Learner Research engine (v1.2.0 item 5).

Learner-corpus tooling in the CAF + CIA tradition:

  * ``learner.errors``  — rule-based error-CANDIDATE finders (EN + AR seed
    rules), framed like the metaphor-candidates pipeline: everything is a
    candidate for human/LLM review, never a confirmed error.
  * ``learner.caf``     — the Complexity-Accuracy-Fluency battery
    (``compute_caf``) and paired-corpus deltas (``caf_delta``).
  * ``learner.service`` — DB plumbing: sentence loading, corpus CAF reports
    grouped by L1/proficiency, and Granger (1998) Contrastive Interlanguage
    Analysis.
"""
from learner.caf import CAFIndices, caf_delta, compute_caf
from learner.errors import (
    AR_RULES,
    EN_RULES,
    ErrorCandidatesResult,
    detect_error_candidates,
    flag_sentence_tokens,
)
from learner.service import CITATIONS, FORMULAS, cia_compare, learner_caf_report, load_sentences

__all__ = [
    "AR_RULES",
    "CITATIONS",
    "EN_RULES",
    "FORMULAS",
    "CAFIndices",
    "ErrorCandidatesResult",
    "caf_delta",
    "cia_compare",
    "compute_caf",
    "detect_error_candidates",
    "flag_sentence_tokens",
    "learner_caf_report",
    "load_sentences",
]
