"""Phase 2 analysis API routes: n-grams, POS, grammar, dependency, discourse, vocabulary, sentiment, metaphor."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from discourse.service import (
    compute_dependency_analysis,
    compute_discourse_analysis,
    compute_grammar_analysis,
    compute_metaphor_candidates,
    compute_ngrams,
    compute_pos_analysis,
    compute_vocab_profile,
)

# v1.2.8 (review #8): the layered sentiment implementation moved to its own
# package (sentiment.service); the endpoint contract is unchanged.
from sentiment.service import compute_sentiment
from storage.models import Corpus
from storage.session import get_session

router = APIRouter()


# --------------------------------------------------------------------------- #
# §8.8 N-grams
# --------------------------------------------------------------------------- #


class NGramRequest(BaseModel):
    n: int = Field(2, ge=2, le=10)
    min_freq: int = Field(5, ge=1)
    min_range: int = Field(1, ge=1, description="Minimum distinct documents (§8.8 lexical bundles)")
    limit: int = Field(200, ge=1, le=1000)
    skip_punct: bool = True
    skip_stop: bool = False


@router.post("/corpora/{cid}/ngrams")
async def ngrams(
    cid: str, body: NGramRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_ngrams(
        session,
        cid,
        n=body.n,
        min_freq=body.min_freq,
        min_range=body.min_range,
        limit=body.limit,
        skip_punct=body.skip_punct,
        skip_stop=body.skip_stop,
    )
    return asdict(r)


# --------------------------------------------------------------------------- #
# §8.11 POS analysis
# --------------------------------------------------------------------------- #


class POSRequest(BaseModel):
    n: int = Field(2, ge=1, le=5, description="POS n-gram size (1=distribution, 2=bigrams, etc.)")
    min_freq: int = Field(2, ge=1)
    limit: int = Field(100, ge=1, le=1000)
    tagset: str = Field("upos", description="upos | ptb | claws7 (en) | calima (ar) - v1.2.0")


@router.post("/corpora/{cid}/pos-analysis")
async def pos_analysis(
    cid: str, body: POSRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    corpus = await session.get(Corpus, cid)
    if not corpus:
        raise HTTPException(404, "Corpus not found")
    # v1.2.0: validate the tagset against the corpus language.
    from nlp.tagsets import is_valid_tagset

    if not is_valid_tagset(body.tagset, corpus.language or "en"):
        from nlp.tagsets import valid_tagsets_for_language

        raise HTTPException(
            422,
            f"Tagset '{body.tagset}' is not valid for a '{corpus.language}' corpus. "
            f"Valid tagsets: {', '.join(valid_tagsets_for_language(corpus.language or 'en'))}.",
        )
    r = await compute_pos_analysis(
        session, cid, n=body.n, min_freq=body.min_freq, limit=body.limit, tagset=body.tagset
    )
    return asdict(r)


# --------------------------------------------------------------------------- #
# §8.11b Semantic analysis — USAS top-level (v1.2.0, Issue 4)
# --------------------------------------------------------------------------- #


class SemanticRequest(BaseModel):
    limit: int = Field(100, ge=1, le=100)


@router.post("/corpora/{cid}/semantic-analysis")
async def semantic_analysis(
    cid: str, body: SemanticRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    """USAS top-level semantic distribution (lexicon-based, experimental)."""
    from discourse.service import compute_semantic_analysis

    corpus = await session.get(Corpus, cid)
    if not corpus:
        raise HTTPException(404, "Corpus not found")
    from nlp.tagsets import load_semantic_lexicon

    if not load_semantic_lexicon(corpus.language or "en"):
        raise HTTPException(
            503,
            "The USAS semantic lexicon for this language is not installed. "
            "See reference-data/tagsets/ in the repository.",
        )
    r = await compute_semantic_analysis(session, cid, limit=body.limit)
    return asdict(r)


# --------------------------------------------------------------------------- #
# §8.12 Grammar analysis
# --------------------------------------------------------------------------- #


class GrammarRequest(BaseModel):
    patterns: list[str] | None = None
    limit: int = Field(50, ge=1, le=500)


@router.post("/corpora/{cid}/grammar")
async def grammar(
    cid: str, body: GrammarRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_grammar_analysis(session, cid, patterns=body.patterns, limit=body.limit)
    return asdict(r)


@router.get("/corpora/{cid}/grammar/patterns")
async def grammar_patterns(cid: str) -> dict:
    """List the available grammar pattern detectors."""
    from discourse.service import GRAMMAR_DETECTORS

    return {"patterns": list(GRAMMAR_DETECTORS.keys())}


# --------------------------------------------------------------------------- #
# §8.13 Dependency analysis
# --------------------------------------------------------------------------- #


class DependencyRequest(BaseModel):
    relation: str = Field("nsubj", description="UD relation: nsubj, obj, iobj, obl, etc.")
    limit: int = Field(100, ge=1, le=1000)


@router.post("/corpora/{cid}/dependencies")
async def dependencies(
    cid: str, body: DependencyRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_dependency_analysis(session, cid, relation=body.relation, limit=body.limit)
    return asdict(r)


# --------------------------------------------------------------------------- #
# §8.13b UD v2 syntax upgrade (v1.2.7, §2)
# --------------------------------------------------------------------------- #


@router.post("/corpora/{cid}/ud-profile")
async def ud_profile(cid: str, session: AsyncSession = Depends(get_session)) -> dict:
    """The 37 UD v2 universal relations profiled by functional group (§2)."""
    from discourse.service import compute_ud_profile

    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_ud_profile(session, cid)
    return asdict(r)


class ValencyRequest(BaseModel):
    lemma: str = Field(..., min_length=1, description="Verb lemma to profile")
    limit: int = Field(20, ge=1, le=100)


@router.post("/corpora/{cid}/valency")
async def valency(
    cid: str, body: ValencyRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    """Observed argument frames (valency) for one verb lemma (§2)."""
    from discourse.service import compute_valency_frames

    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    try:
        r = await compute_valency_frames(
            session, cid, lemma=body.lemma, limit=body.limit
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return asdict(r)


@router.get("/corpora/{cid}/sentences")
async def sentences(
    cid: str,
    limit: int = 30,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Paginated sentence index (tree picker)."""
    from discourse.service import list_corpus_sentences

    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await list_corpus_sentences(session, cid, limit=min(limit, 200), offset=max(offset, 0))
    return asdict(r)


class SentenceTreeRequest(BaseModel):
    doc: str
    sent: int = Field(..., ge=0)


@router.post("/corpora/{cid}/sentence-tree")
async def sentence_tree(
    cid: str, body: SentenceTreeRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    """Head/rel tokens for one sentence — rendered as an arc diagram (§2)."""
    from discourse.service import compute_sentence_tree

    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    try:
        r = await compute_sentence_tree(session, cid, doc=body.doc, sent=body.sent)
    except ValueError as e:
        msg = str(e)
        if msg.startswith("sentence_not_found:"):
            raise HTTPException(404, "Sentence not found in this corpus") from e
        raise HTTPException(400, msg) from e
    return asdict(r)


# v1.2.8 (review #2): KWIC-style concordance over dependency hits.
class DepConcordanceRequest(BaseModel):
    node_query: str = Field("", description="Node word/lemma (concordancer semantics: wildcard and regex supported).")
    level: str = Field("word", description="word | lemma")
    regex: bool = False
    case_sensitive: bool = False
    relation: str | None = Field(None, description="Filter by the node's base UD relation (raw subtypes match too).")
    pos: str | None = Field(None, description="Filter by the node's UPOS tag (e.g. NOUN, VERB).")
    window: int = Field(6, ge=1, le=20)
    limit: int = Field(100, ge=1, le=1000)


@router.post("/corpora/{cid}/dep-concordance")
async def dep_concordance(
    cid: str, body: DepConcordanceRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    """One row per dependency hit: left | node | right | head | relation | source."""
    from discourse.service import compute_dep_concordance

    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    try:
        r = await compute_dep_concordance(
            session,
            cid,
            node_query=body.node_query,
            level=body.level,
            regex=body.regex,
            case_sensitive=body.case_sensitive,
            relation=body.relation,
            pos=body.pos,
            window=body.window,
            limit=body.limit,
        )
    except ValueError as e:
        msg = str(e)
        if msg.startswith("dep_concordance_empty_query:"):
            raise HTTPException(
                422,
                "Give a node query, a relation filter, or a POS filter - "
                "at least one is required.",
            ) from e
        raise HTTPException(400, msg) from e
    return asdict(r)


# --------------------------------------------------------------------------- #
# §8.15 Discourse analysis — multi-taxonomy (v1.2.6)
# --------------------------------------------------------------------------- #


class DiscourseRequest(BaseModel):
    taxonomy: str = Field(
        "hyland2005",
        description=(
            "hyland2005 (default) | hallidayhasan1976 | martinwhite2005 | "
            "cialdini2007 (Influence, Revised Ed., ch.2-7) | "
            "usas (CLAWS/USAS top-level semantic tagset) | sfg_hm2014 "
            "(SFG Transitivity & Modality)"
        ),
    )
    # v1.2.7 (§3): optional keyness comparison — when set, the same taxonomy
    # is also run over this corpus and every category row gains the §12
    # keyness battery (LL, Log Ratio, %DIFF, simple maths) + a Cochran
    # low-power warning. Omit for the v1.2.6 single-corpus response shape.
    compare_corpus_id: str | None = Field(
        None, description="Optional second corpus id to compute per-category keyness against."
    )


@router.get("/corpora/{cid}/discourse/taxonomies")
async def discourse_taxonomies(cid: str) -> dict:
    """Registry of supported discourse taxonomies (keys, names, citations)."""
    from discourse.service import discourse_taxonomy_list

    return {"taxonomies": discourse_taxonomy_list()}


# v1.2.8 (review #1): resource health for the optional persuasion-index lens.
# This is a STATUS endpoint (always 200): it tells the UI whether the package
# is installed and, when it is, which optional resources are active versus
# degraded to neutral baselines - instead of a blanket "not installed" error.
@router.get("/discourse/persuasion/health")
async def persuasion_health() -> dict:
    """persuasion-index resource status (mirrors `persuasion-index doctor --json`)."""
    from discourse.service import PERSUASION_CITATION

    try:
        import persuasion_index
    except ImportError:
        return {
            "installed": False,
            "version": None,
            "install_hint": (
                "pip install persuasion-index (Apache-2.0, Wang & Gong 2026) "
                "or pip install -e '.[persuasion]' in the engine directory"
            ),
            "resources_required": False,
            "policy": (
                "The lens ships on the package's bundled lexicons; optional "
                "resources only refine specific subfeatures."
            ),
            "complete": False,
            "missing": [],
            "resources": {},
            "citation": PERSUASION_CITATION,
        }

    import importlib.metadata

    from persuasion_index import check_resources, missing_resources

    try:
        version = persuasion_index.__version__ or importlib.metadata.version(
            "persuasion-index"
        )
    except Exception:  # pragma: no cover — version metadata always present in practice
        version = None

    resources = check_resources()
    missing = missing_resources()

    # v1.2.9: per-resource "how to enable" metadata — the env var
    # persuasion-index honours, the canonical filename, the official
    # source, and the license note. The four data-backed resources are
    # license-restricted (never bundled), so the panel must be able to
    # teach the user exactly how to turn each one on.
    from app.settings import get_settings
    from discourse.pi_resources import install_hints, resources_dir_hint

    _settings = get_settings()

    return {
        "installed": True,
        "version": version,
        "install_hint": None,
        "resources_required": False,
        "policy": (
            "Scores are computed with the bundled lexicons; optional resources "
            "marked unavailable degrade their subfeatures to neutral baselines. "
            "Dimension comparisons across texts are only valid when scored with "
            "the same PI version and resource configuration."
        ),
        "complete": len(missing) == 0,
        "missing": missing,
        "resources": resources,
        # v1.2.9: install guidance for license-restricted optional resources.
        "resources_dir": resources_dir_hint(_settings),
        "install_hints": install_hints(_settings),
        "citation": PERSUASION_CITATION,
    }


@router.post("/corpora/{cid}/discourse")
async def discourse(
    cid: str,
    body: DiscourseRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Discourse analysis under a named taxonomy (§8.15).

    Body is OPTIONAL for backward compatibility: a bodyless POST keeps the
    default Hyland 2005 metadiscourse lens.
    """
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    taxonomy = (body.taxonomy if body else "hyland2005") or "hyland2005"
    compare_corpus_id = body.compare_corpus_id if body else None
    if compare_corpus_id:
        compare_corpus = await session.get(Corpus, compare_corpus_id)
        if not compare_corpus:
            raise HTTPException(
                404, f"Comparison corpus not found: {compare_corpus_id}"
            )
    try:
        r = await compute_discourse_analysis(
            session, cid, taxonomy=taxonomy, compare_corpus_id=compare_corpus_id
        )
    except ValueError as e:
        msg = str(e)
        if msg.startswith("usas_lexicon_missing:"):
            lang = msg.split(":", 1)[1]
            raise HTTPException(
                503,
                f"The USAS semantic lexicon for '{lang}' is not installed. "
                "See reference-data/tagsets/ in the repository, or use the "
                "Grammatical tagsets setting to check availability.",
            ) from e
        if msg.startswith("persuasion_index_missing:"):
            raise HTTPException(
                503,
                "The persuasion-index package is not installed in this "
                "engine. Install it with `pip install persuasion-index` "
                "(Apache-2.0, Wang & Gong 2026) to enable the Persuasion "
                "Index lens.",
            ) from e
        raise HTTPException(400, msg) from e
    return asdict(r)


# --------------------------------------------------------------------------- #
# §8.10 Vocabulary profiling
# --------------------------------------------------------------------------- #


class VocabProfileRequest(BaseModel):
    rare_threshold: int = Field(
        1, ge=1, description="Words appearing <= this many times are 'rare'"
    )
    limit: int = Field(100, ge=1, le=500)


@router.post("/corpora/{cid}/vocab-profile")
async def vocab_profile(
    cid: str, body: VocabProfileRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_vocab_profile(
        session, cid, rare_threshold=body.rare_threshold, limit=body.limit
    )
    return asdict(r)


# --------------------------------------------------------------------------- #
# §8.18 Sentiment analysis
# --------------------------------------------------------------------------- #


@router.post("/corpora/{cid}/sentiment")
async def sentiment(cid: str, session: AsyncSession = Depends(get_session)) -> dict:
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_sentiment(session, cid)
    return asdict(r)


# --------------------------------------------------------------------------- #
# §8.17 Metaphor candidates
# --------------------------------------------------------------------------- #


class MetaphorRequest(BaseModel):
    limit: int = Field(50, ge=1, le=500)


@router.post("/corpora/{cid}/metaphor-candidates")
async def metaphor_candidates(
    cid: str, body: MetaphorRequest, session: AsyncSession = Depends(get_session)
) -> dict:
    """Find metaphor candidates (§8.17). The LLM triages these via the
    metaphor_triage tool, and the human must verify before any candidate
    counts as a confirmed metaphor in export/statistics."""
    if not await session.get(Corpus, cid):
        raise HTTPException(404, "Corpus not found")
    r = await compute_metaphor_candidates(session, cid, limit=body.limit)
    return asdict(r)
