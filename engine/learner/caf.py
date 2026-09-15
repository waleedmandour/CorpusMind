"""CAF battery — Complexity, Accuracy and Fluency indices (v1.2.0 item 5).

The CAF construct is the standard operationalization of L2 proficiency in
learner-corpus research: **Complexity** (lexical richness + syntactic
complexity), **Accuracy** (error density) and **Fluency** (here: length-based
proxies only — v1.2.0 has no temporal speech data, so true fluency indices are
out of scope by construction).

Lineage and honesty, stated up front:
  * Lexical diversity reuses the §12 measures verbatim (TTR, MATTR, MTLD,
    HD-D, Guiraud) — McCarthy & Jarvis 2010 for MTLD/HD-D; Lu 2012 for the
    lexical-richness-to-quality framing.
  * Syntactic complexity follows the Lu (2010) automated-indices lineage in a
    drastically simplified form: clause heads = VERB/AUX tokens with a
    subordinate/conjoined clause relation (acl, advcl, ccomp, xcomp, csubj,
    relcl variants, conj). No T-units, no full Lu (2010) battery — yet.
  * Accuracy is a HEURISTIC PROXY only: a sentence counts as "error-free"
    when no seed rule from ``learner.errors`` fires on it. Those rules are
    candidates-for-review, not validated errors (see errors.py), so every
    accuracy number below is a lower-bound-ish proxy and MUST be read with
    the notes attached.
  * ``root_type_ratio`` is an Arabic-specific morphology index (distinct roots
    / tokens) computed from the ``morph`` layer ("root=X|...") produced by the
    Arabic pipeline.

Everything is pure Python (stdlib ``statistics``); no scipy, no numpy.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field, fields

from app.logging import get_logger
from learner.errors import flag_sentence_tokens
from stats.measures import guiraud, hd_d, mattr, mtld, type_token_ratio

log = get_logger(__name__)

# UD relations whose head opens a (subordinate or conjoined) clause. spaCy's
# en_core_web_sm emits the legacy 'relcl' label; UD v2 uses 'acl:relcl'.
_CLAUSE_RELS = {"acl", "advcl", "ccomp", "xcomp", "csubj", "csubj:pass",
                "acl:relcl", "relcl", "conj"}

_ARABIC_CHAR = re.compile(r"[\u0600-\u06FF]")

_ROOT_PART = re.compile(r"(?:^|\|)root=([^|]+)")

_SENT_LEN_BUCKETS = (("1-5", 1, 5), ("6-10", 6, 10), ("11-15", 11, 15),
                     ("16-20", 16, 20), ("21+", 21, None))

_ACCURACY_DISCLAIMER = (
    "Accuracy indices are HEURISTIC PROXIES computed from seed rule-based "
    "error candidates (learner.errors) — NOT validated error counts. "
    "Human/LLM verification is required before reporting them."
)
_COMPLEXITY_DISCLAIMER = (
    "Complexity indices are automated approximations (Lu 2010/2012 lineage, "
    "simplified clause detection); interpret alongside the formulas panel."
)


@dataclass
class CAFIndices:
    """One CAF measurement over a set of sentences. All ratio fields are
    ``float | None`` — None means the input lacked the annotation layer the
    index needs (dependency parse, morphology), never "zero"."""

    documents: int
    tokens: int
    sentences: int
    # --- complexity: lexical diversity (on lowercased token text) ---
    ttr: float
    mattr: float
    mtld: float
    hd_d: float
    guiraud: float
    # --- complexity: syntactic (length-based + clause-based) ---
    mean_sentence_length: float
    sentence_length_stdev: float
    mean_clause_length: float | None
    clauses_per_sentence: float | None
    mean_word_length: float
    root_type_ratio: float | None
    # --- accuracy (HEURISTIC PROXIES) ---
    error_free_sentence_ratio: float | None
    error_candidates_per_100: float | None
    spelling_candidate_rate: float | None
    # --- distribution + provenance ---
    sentence_length_histogram: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _sentence_length_bucket(n: int) -> str:
    for label, lo, hi in _SENT_LEN_BUCKETS:
        if n >= lo and (hi is None or n <= hi):
            return label
    return "1-5"


def _root_type_ratio(tokens: list[dict]) -> float | None:
    """Distinct morphological roots / tokens from the 'root=X|...' morph layer.

    None when no token carries a morph layer at all (English spaCy models
    don't emit roots; the Arabic pipeline does)."""
    roots: set[str] = set()
    has_morph = False
    for tok in tokens:
        morph = tok.get("morph") or ""
        if morph:
            has_morph = True
        m = _ROOT_PART.search(morph)
        if m and m.group(1):
            roots.add(m.group(1))
    if not has_morph or not tokens:
        return None
    return len(roots) / len(tokens)


def compute_caf(sentences: list[list[dict]], *, language: str | None = None) -> CAFIndices:
    """Compute the CAF battery over ``sentences``.

    ``sentences`` is a list of per-sentence token lists; each token is a dict
    with ``text`` plus optional ``lemma``/``pos``/``morph``/``dep_rel``/
    ``token_idx``/``document_id`` keys (the shape produced by
    ``learner.service.load_sentences`` and by the raw-text pipeline bridge).

    ``language`` selects the error-candidate rule set ('ar*' → Arabic rules,
    else English rules). When None it is auto-detected from the script of the
    token texts (any Arabic-script token → 'ar').

    Notes on the None policy:
      * If NO token carries a non-placeholder ``dep_rel`` (blank spaCy fallback
        and the current Arabic pipeline produce ``dep``/``""``), the clause
        indices are None and a note says dependency parsing was unavailable.
      * ``root_type_ratio`` is None when no morph layer exists.
    """
    # Flatten, preserving sentence order.
    flat: list[dict] = [tok for sent in sentences for tok in sent]
    n_tokens = len(flat)
    n_sents = len(sentences)

    texts = [(t.get("text") or "") for t in flat]
    lowered = [t.lower() for t in texts]

    if language is None:
        language = "ar" if any(_ARABIC_CHAR.search(t) for t in texts if t) else "en"

    notes: list[str] = [_ACCURACY_DISCLAIMER, _COMPLEXITY_DISCLAIMER]

    # --- counts ------------------------------------------------------------
    doc_ids = {t.get("document_id") for t in flat if t.get("document_id")}
    documents = len(doc_ids) if doc_ids else (1 if n_tokens else 0)

    # --- length / fluency-proxy indices ------------------------------------
    sent_lengths = [len(s) for s in sentences]
    mean_sentence_length = (sum(sent_lengths) / n_sents) if n_sents else 0.0
    sentence_length_stdev = statistics.stdev(sent_lengths) if n_sents >= 2 else 0.0
    histogram: dict[str, int] = {}
    for label, _lo, _hi in _SENT_LEN_BUCKETS:
        histogram[label] = 0
    for n in sent_lengths:
        histogram[_sentence_length_bucket(n)] += 1

    mean_word_length = (
        sum(len(t) for t in texts) / n_tokens if n_tokens else 0.0
    )

    # --- complexity: lexical diversity --------------------------------------
    ttr = round(type_token_ratio(lowered), 4)
    mattr_v = round(mattr(lowered), 4)
    mtld_v = round(mtld(lowered), 4)
    hd_d_v = round(hd_d(lowered), 4)
    guiraud_v = round(guiraud(lowered), 4)

    # --- complexity: syntactic (clause detection) ---------------------------
    has_parse = any((t.get("dep_rel") or "") not in ("", "dep") for t in flat)
    if has_parse:
        clause_heads = [
            t for t in flat
            if (t.get("dep_rel") or "") in _CLAUSE_RELS
            and str(t.get("pos") or "").startswith(("VERB", "AUX"))
        ]
        n_clauses = len(clause_heads)
        clauses_per_sentence = round(n_clauses / n_sents, 4) if n_sents else 0.0
        mean_clause_length = round(n_tokens / n_clauses, 4) if n_clauses else None
    else:
        n_clauses = 0
        clauses_per_sentence = None
        mean_clause_length = None
        notes.append(
            "Dependency parsing unavailable for this language — clause indices omitted."
        )

    # --- morphology: root-type ratio ----------------------------------------
    root_ratio = _root_type_ratio(flat)
    if root_ratio is None:
        notes.append(
            "No morphological root layer on these tokens — root_type_ratio omitted."
        )

    # --- accuracy proxy (heuristic!) ----------------------------------------
    # The error-free boolean is delegated to learner.errors.flag_sentence_tokens
    # (the documented primitive); the density counts below reuse the same rule
    # set to attribute firings per token.
    error_free = 0
    total_flagged = 0
    spelling_flagged = 0
    for sent in sentences:
        if not flag_sentence_tokens(sent, language):
            error_free += 1
        firings = _sentence_firings(sent, language)
        total_flagged += len({tok_idx for tok_idx, _rid, _r in firings})
        spelling_flagged += sum(1 for _i, rid, _r in firings if rid == "en_spelling")
    error_free_sentence_ratio = round(error_free / n_sents, 4) if n_sents else None
    error_candidates_per_100 = (
        round(total_flagged / n_tokens * 100.0, 4) if n_tokens else None
    )
    spelling_candidate_rate = (
        round(spelling_flagged / n_tokens, 4) if n_tokens else None
    )

    log.info(
        "learner_caf_computed", tokens=n_tokens, sentences=n_sents,
        language=language, error_free_ratio=error_free_sentence_ratio,
    )
    return CAFIndices(
        documents=documents,
        tokens=n_tokens,
        sentences=n_sents,
        ttr=ttr,
        mattr=mattr_v,
        mtld=mtld_v,
        hd_d=hd_d_v,
        guiraud=guiraud_v,
        mean_sentence_length=round(mean_sentence_length, 4),
        sentence_length_stdev=round(sentence_length_stdev, 4),
        mean_clause_length=mean_clause_length,
        clauses_per_sentence=clauses_per_sentence,
        mean_word_length=round(mean_word_length, 4),
        root_type_ratio=root_ratio,
        error_free_sentence_ratio=error_free_sentence_ratio,
        error_candidates_per_100=error_candidates_per_100,
        spelling_candidate_rate=spelling_candidate_rate,
        sentence_length_histogram=histogram,
        notes=notes,
    )


def _sentence_firings(sent: list[dict], language: str) -> list[tuple[int, str, str]]:
    """All (token_idx, rule_id, reason) firings for one sentence, across rules."""
    from learner import errors as _errors

    out: list[tuple[int, str, str]] = []
    rules = _errors._rules_for(language)
    for rid, rule in rules.items():
        out.extend(rule["detect"](sent))
    return out


def caf_delta(target: CAFIndices, baseline: CAFIndices) -> dict:
    """Per-field difference target − baseline for shared numeric fields.

    Rounded to 4 decimals; None when either side is None (the CAF None policy
    means "index not computable", and subtracting a non-computable index would
    silently fabricate a number).
    """
    out: dict[str, float | int | None] = {}
    for f in fields(CAFIndices):
        if f.name in ("notes", "sentence_length_histogram"):
            continue
        t = getattr(target, f.name)
        b = getattr(baseline, f.name)
        if isinstance(t, (int, float)) and isinstance(b, (int, float)) \
                and not isinstance(t, bool) and not isinstance(b, bool):
            out[f.name] = round(t - b, 4)
        else:
            out[f.name] = None
    return out
