"""Learner Research service — DB plumbing for CAF reports and CIA (v1.2.0 item 5).

Two entry points:

  * :func:`learner_caf_report` — the Complexity-Accuracy-Fluency battery over
    the latest annotation version of a learner corpus, optionally grouped by
    the learner facets (L1, CEFR proficiency) with the per-document
    ``Document.meta`` override convention (meta value wins over the corpus
    default; neither → "(unspecified)").
  * :func:`cia_compare` — Granger's (1998) **Contrastive Interlanguage
    Analysis**: compare learner language (L2) against a target-language
    reference *and* against other learner varieties. The keyness half reuses
    the existing §8.7 machinery verbatim (``stats.service.compute_keyness`` or
    the bundled-list bridge); the CAF half reuses ``learner.caf``.

The middle layer, :func:`load_sentences`, is the shared token loader: it
returns sentences in exactly the shape ``learner.caf.compute_caf`` consumes,
plus per-token ``document_id``/``sentence_idx`` provenance fields.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from learner.caf import CAFIndices, caf_delta, compute_caf
from stats.service import _latest_version_id
from storage.models import Corpus, Document, Token

log = get_logger(__name__)

# --------------------------------------------------------------------------- #
# Formulas + citations surfaced with every report (§4 Principle 3: never show
# a number without its definition)
# --------------------------------------------------------------------------- #

FORMULAS: dict[str, str] = {
    "ttr": "TTR = types / tokens (on lowercased word forms)",
    "mattr": "MATTR: mean TTR over every consecutive 50-token window (Covington & McFall 2010)",
    "mtld": "MTLD: tokens per factor run where running TTR ≤ 0.72, forward+backward averaged (McCarthy & Jarvis 2010)",
    "hd_d": "HD-D: hypergeometric distribution diversity over 42-token samples (McCarthy & Jarvis 2010)",
    "guiraud": "Guiraud's Root TTR = types / √tokens",
    "mean_sentence_length": "mean tokens per sentence (punctuation excluded)",
    "sentence_length_stdev": "sample standard deviation of sentence lengths in tokens",
    "mean_clause_length": "tokens / clause-head tokens (VERB/AUX heads of acl|advcl|ccomp|xcomp|csubj|relcl|conj)",
    "clauses_per_sentence": "clause-head tokens / sentences",
    "mean_word_length": "mean character length of word forms",
    "root_type_ratio": "distinct morphological roots ('root=X|…' layer) / tokens — Arabic only",
    "error_free_sentence_ratio": "sentences with no seed-rule firing / sentences — HEURISTIC PROXY, not validated accuracy",
    "error_candidates_per_100": "unique rule-flagged tokens per 100 tokens — HEURISTIC PROXY",
    "spelling_candidate_rate": "spelling-rule flagged tokens / tokens — HEURISTIC PROXY",
}

CITATIONS: list[str] = [
    "Housen, A., Kuiken, F., & Vedder, I. (Eds.) (2012). Dimensions of L2 "
    "Performance and Proficiency: Complexity, Accuracy and Fluency. John Benjamins.",
    "Crosslinguistic CAF volume (2022) — Complexity, Accuracy and Fluency "
    "approaches across languages, as adopted in the CorpusMind v1.2.0 plan.",
    "Lu, X. (2010). Automatic analysis of syntactic complexity in second "
    "language writing. International Journal of Applied Linguistics, 20(1), 47–74.",
    "Lu, X. (2012). The relationship of lexical richness to the quality of ESL "
    "texts. Journal of Second Language Writing, 21(2), 109–125.",
    "McCarthy, P. M., & Jarvis, S. (2010). MTLD, vocd-D, and HD-D: A validation "
    "study. Behavior Research Methods, 42(2), 381–392.",
    "Covington, M. A., & McFall, J. D. (2010). Cutting the Gordian knot: The "
    "moving-average type–token ratio. Behavior Research Methods, 42(4), 861–865.",
    "Granger, S. (1998). The computer learner corpus: A versatile new source of "
    "data for SLA research. In S. Granger (Ed.), Learner English on Computer. "
    "Addison Wesley Longman.",
]

# Keyness citations reused by cia_compare.
_KEYNESS_CITATIONS: list[str] = [
    "Dunning, T. (1993). Accurate methods for the statistics of surprise and "
    "coincidence. Computational Linguistics, 19(1), 61–74. (log-likelihood)",
    "Hardie, A. (2014). Log Ratio — an informal introduction. ESRC Centre for "
    "Corpus Approaches to Social Science. (effect size)",
    "Gabrielatos, C., & Marchi, A. (2012). Keyness: Appropriate metrics and "
    "practical issues. AAICLaB, University of Pisa. (%DIFF)",
    "Kilgarriff, A. (2009). Simple maths for keywords. In Proceedings of the "
    "Corpus Linguistics 2009 conference.",
]

_CIA_CITATION: str = (
    "Granger, S. (1998). The computer learner corpus — Chapter introduces the "
    "Contrastive Interlanguage Analysis (CIA) design: learner L2 vs native "
    "target language, and learner L2 vs other learner varieties."
)

_UNSPECIFIED = "(unspecified)"


# --------------------------------------------------------------------------- #
# Sentence loader
# --------------------------------------------------------------------------- #


async def load_sentences(
    session: AsyncSession,
    corpus_id: str,
    *,
    document_ids: list[str] | None = None,
) -> tuple[list[list[dict]], dict]:
    """Load the latest annotation version's sentences in ``compute_caf`` shape.

    Returns ``(sentences, meta)`` where each sentence is a list of token dicts
    ``{text, lemma, pos, morph, dep_rel, token_idx, document_id, sentence_idx}``
    ordered by (document_id, sentence_idx, token_idx), and ``meta`` is
    ``{language, l1, proficiency, document_count}`` (corpus-level facet
    defaults; per-document overrides are the caller's concern — see
    :func:`learner_caf_report`). Punctuation and whitespace tokens are excluded.
    An empty list with ``document_count: 0`` means no ingested version.
    """
    corpus = await session.get(Corpus, corpus_id)
    language = corpus.language if corpus else "en"
    l1 = (corpus.l1 if corpus else "") or ""
    proficiency = (corpus.proficiency if corpus else "") or ""

    version_id = await _latest_version_id(session, corpus_id)
    meta = {
        "language": language,
        "l1": l1,
        "proficiency": proficiency,
        "document_count": 0,
    }
    if not version_id:
        return [], meta

    stmt = (
        select(
            Token.document_id,
            Token.sentence_idx,
            Token.token_idx,
            Token.text,
            Token.lemma,
            Token.pos,
            Token.morph,
            Token.dep_rel,
        )
        .where(
            Token.version_id == version_id,
            Token.is_punct == False,  # noqa: E712
            Token.pos != "SPACE",
        )
        .order_by(Token.document_id, Token.sentence_idx, Token.token_idx)
    )
    if document_ids is not None:
        stmt = stmt.where(Token.document_id.in_(document_ids))

    rows = (await session.execute(stmt)).all()
    grouped: dict[tuple[str, int], list[dict]] = defaultdict(list)
    docs: set[str] = set()
    for doc_id, sent_idx, tok_idx, text, lemma, pos, morph, dep_rel in rows:
        docs.add(doc_id)
        grouped[(doc_id, sent_idx)].append(
            {
                "text": text,
                "lemma": lemma,
                "pos": pos,
                "morph": morph,
                "dep_rel": dep_rel,
                "token_idx": tok_idx,
                "document_id": doc_id,
                "sentence_idx": sent_idx,
            }
        )
    sentences = [grouped[key] for key in sorted(grouped.keys())]
    meta["document_count"] = len(docs)
    return sentences, meta


# --------------------------------------------------------------------------- #
# CAF report (overall + per learner facet)
# --------------------------------------------------------------------------- #


def _facet_group(meta: dict | None, facet: str, corpus_default: str) -> str:
    """Document facet value: Document.meta overrides the corpus default."""
    value = (meta or {}).get(facet)
    if value not in (None, ""):
        return str(value)
    return corpus_default or _UNSPECIFIED


def _caf_block(sentences: list[list[dict]], language: str) -> dict:
    """asdict(CAFIndices) plus the token count of the block."""
    caf = compute_caf(sentences, language=language)
    return asdict(caf)


async def learner_caf_report(
    session: AsyncSession,
    corpus_id: str,
    *,
    group_by: str = "none",
    document_ids: list[str] | None = None,
) -> dict:
    """Overall CAF battery + optional per-facet (L1 / proficiency) grouping.

    Grouping follows the learner-facet convention: ``Document.meta[facet]``
    overrides the ``Corpus.l1`` / ``Corpus.proficiency`` column default;
    documents with neither are grouped under "(unspecified)".
    """
    corpus = await session.get(Corpus, corpus_id)
    if not corpus:
        raise ValueError(f"Corpus '{corpus_id}' not found")

    sentences, _meta = await load_sentences(session, corpus_id, document_ids=document_ids)

    # Document → facet group map (for partitioning sentences below).
    doc_group: dict[str, str] = {}
    if group_by in ("l1", "proficiency"):
        corpus_default = corpus.l1 if group_by == "l1" else corpus.proficiency
        docs_stmt = select(Document.id, Document.meta).where(Document.corpus_id == corpus_id)
        if document_ids is not None:
            docs_stmt = docs_stmt.where(Document.id.in_(document_ids))
        for doc_id, dmeta in (await session.execute(docs_stmt)).all():
            doc_group[doc_id] = _facet_group(dmeta, group_by, corpus_default)

    groups: dict[str, list[list[dict]]] = defaultdict(list)
    group_docs: dict[str, set[str]] = defaultdict(set)
    for sent in sentences:
        doc_id = sent[0]["document_id"]
        name = doc_group.get(doc_id, _UNSPECIFIED) if doc_group else _UNSPECIFIED
        groups[name].append(sent)
        group_docs[name].add(doc_id)

    language = corpus.language or "en"
    overall_caf = _caf_block(sentences, language)

    group_rows = []
    if group_by in ("l1", "proficiency"):
        group_rows = [
            {
                "name": name,
                "documents": len(group_docs[name]),
                "tokens": sum(len(s) for s in groups[name]),
                "caf": _caf_block(groups[name], language),
            }
            for name in sorted(groups.keys())
        ]

    return {
        "corpus": {
            "id": corpus.id,
            "name": corpus.name,
            "language": language,
            "l1": corpus.l1 or "",
            "proficiency": corpus.proficiency or "",
        },
        "group_by": group_by if group_by in ("l1", "proficiency") else "none",
        "groups": group_rows,
        "overall": {
            "documents": overall_caf["documents"],
            "tokens": overall_caf["tokens"],
            "caf": overall_caf,
        },
        "formulas": FORMULAS,
        "citations": CITATIONS,
    }


# --------------------------------------------------------------------------- #
# Contrastive Interlanguage Analysis (Granger 1998)
# --------------------------------------------------------------------------- #


def _corpus_block(corpus: Corpus, sentences: list[list[dict]]) -> tuple[dict, CAFIndices]:
    """Corpus facet info + CAF block, returning the CAFIndices object too so
    callers can compute deltas without re-parsing asdict output."""
    caf = compute_caf(sentences, language=corpus.language or "en")
    return (
        {
            "corpus": {
                "id": corpus.id,
                "name": corpus.name,
                "language": corpus.language or "en",
                "l1": corpus.l1 or "",
                "proficiency": corpus.proficiency or "",
            },
            "caf": asdict(caf),
        },
        caf,
    )


async def cia_compare(
    session: AsyncSession,
    corpus_id: str,
    *,
    reference_corpus_id: str | None = None,
    reference_list: str | None = None,
    compare_corpus_id: str | None = None,
    min_freq: int = 5,
    limit: int = 100,
) -> dict:
    """Contrastive Interlanguage Analysis (Granger 1998).

    Three optional arms, all reusable machinery:

    * ``reference_corpus_id`` — keyness of the learner corpus against an
      uploaded reference Corpus (``stats.service.compute_keyness``), plus a
      CAF delta reference-vs-target.
    * ``reference_list`` — keyness against a *bundled* reference frequency
      list (``reference_corpus.keyness_bridge.compute_keyness_with_reference_list``).
    * ``compare_corpus_id`` — a second learner corpus: CAF delta
      compare-vs-target (the "learner variety vs learner variety" arm).

    ValueError from the keyness layer (missing annotation version, etc.) is
    surfaced as ``HTTPException(422)`` so the UI can explain *why* the
    comparison is empty rather than pretending it succeeded (same contract as
    the §8.7 keyness endpoint).
    """
    from fastapi import HTTPException

    corpus = await session.get(Corpus, corpus_id)
    if not corpus:
        raise ValueError(f"Corpus '{corpus_id}' not found")

    warnings: list[str] = []
    keyness: dict | None = None

    # --- keyness arm --------------------------------------------------------
    if reference_corpus_id:
        try:
            kr = await _keyness_against_corpus(
                session, corpus_id, reference_corpus_id, min_freq=min_freq, limit=limit
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        keyness = asdict(kr)
        warnings.extend(kr.warnings or [])
    elif reference_list:
        from reference_corpus.keyness_bridge import compute_keyness_with_reference_list

        try:
            kr = await compute_keyness_with_reference_list(
                session, corpus_id, reference_list, min_freq=min_freq, limit=limit
            )
        except FileNotFoundError as e:
            raise HTTPException(
                status_code=404,
                detail=f"Reference list '{reference_list}' is not installed. "
                f"Use the Reference Corpora panel to install a bundled reference.",
            ) from e
        keyness = asdict(kr)
        warnings.extend(kr.warnings or [])

    # --- CAF arms -----------------------------------------------------------
    target_sentences, _tmeta = await load_sentences(session, corpus_id)
    target, target_caf = _corpus_block(corpus, target_sentences)
    if not target_sentences:
        warnings.append(
            "Target corpus has no ingested annotation version — CAF indices are empty."
        )

    reference: dict | None = None
    compare: dict | None = None
    deltas: dict[str, dict] = {}

    if reference_corpus_id:
        ref_corpus = await session.get(Corpus, reference_corpus_id)
        if not ref_corpus:
            raise ValueError(f"Reference corpus '{reference_corpus_id}' not found")
        ref_sentences, _ = await load_sentences(session, reference_corpus_id)
        reference, ref_caf = _corpus_block(ref_corpus, ref_sentences)
        deltas["reference_vs_target"] = caf_delta(ref_caf, target_caf)

    if compare_corpus_id:
        cmp_corpus = await session.get(Corpus, compare_corpus_id)
        if not cmp_corpus:
            raise ValueError(f"Compare corpus '{compare_corpus_id}' not found")
        cmp_sentences, _ = await load_sentences(session, compare_corpus_id)
        compare, cmp_caf = _corpus_block(cmp_corpus, cmp_sentences)
        deltas["compare_vs_target"] = caf_delta(cmp_caf, target_caf)

    if keyness is None:
        warnings.append(
            "No keyness arm requested — pass reference_corpus_id (uploaded "
            "reference corpus) or reference_list (bundled reference) for the "
            "corpus-contrast half of CIA."
        )

    citations = [_CIA_CITATION, *_KEYNESS_CITATIONS]
    log.info(
        "learner_cia_compare", corpus_id=corpus_id,
        reference=reference_corpus_id, reference_list=reference_list,
        compare=compare_corpus_id,
    )
    return {
        "target": target,
        "reference": reference,
        "compare": compare,
        "keyness": keyness,
        "deltas": deltas,
        "warnings": warnings,
        "citations": citations,
    }


async def _keyness_against_corpus(
    session: AsyncSession,
    target_corpus_id: str,
    reference_corpus_id: str,
    *,
    min_freq: int,
    limit: int,
):
    """Import-lazy wrapper so importing learner.service never pulls the whole
    stats stack before the app is ready (mirrors analysis.py's usage)."""
    from stats.service import compute_keyness

    return await compute_keyness(
        session, target_corpus_id, reference_corpus_id,
        min_freq=min_freq, limit=limit,
    )
