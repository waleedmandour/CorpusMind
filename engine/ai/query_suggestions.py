"""AI Assistant query suggestions — Issue 2.

Two layers of suggestions:

  1. **Pre-fabricated** — a static catalogue of research-question templates
     covering the standard corpus-linguistics analysis types (frequency,
     collocation, keyness, concordance, dispersion, …). These are ALWAYS
     visible in the Assistant UI, even when no corpus is loaded or no LLM
     is available. They give the user a "what can I ask?" affordance.

  2. **Dynamic** — LLM-generated suggestions that adapt to the currently
     loaded corpus and (optionally) the most recent analysis context.
     Generated on demand via ``generate_dynamic_queries``. Falls back
     gracefully to the pre-fabricated list when:
       - no corpus is loaded
       - no LLM provider is healthy
       - the LLM returns malformed output

The two layers are merged + de-duplicated by the API endpoint so the UI
gets one ordered list: pre-fabricated first (the "always there" set),
then dynamic (the "explore further" set).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Pre-fabricated query catalogue
# --------------------------------------------------------------------------- #


QueryCategory = Literal[
    "frequency", "collocation", "keyness", "concordance", "dispersion",
    "ngrams", "pos", "compare", "explore", "methodology",
]


@dataclass(frozen=True, slots=True)
class QueryTemplate:
    """One pre-fabricated research question the user can click to send."""

    id: str
    """Stable identifier (used for analytics + customization)."""

    category: QueryCategory
    """Used to group suggestions in the UI."""

    label_en: str
    """Short label shown in the UI."""

    label_ar: str
    """Arabic label for RTL mode."""

    query_en: str
    """The actual prompt sent to the Assistant in English mode."""

    query_ar: str
    """The actual prompt sent to the Assistant in Arabic mode."""

    requires_corpus: bool = True
    """If True, the UI greys out this suggestion when no corpus is loaded."""

    requires_reference: bool = False
    """If True, the UI greys out this suggestion when no reference corpus
    is installed for the active corpus's language."""

    description: str = ""
    """One-sentence explanation of what this query is good for."""


PREFABRICATED_QUERIES: list[QueryTemplate] = [
    # --- Frequency ---
    QueryTemplate(
        id="freq-top10",
        category="frequency",
        label_en="Top 10 most frequent words",
        label_ar="أكثر 10 كلمات تكراراً",
        query_en="What are the top 10 most frequent words in this corpus?",
        query_ar="ما هي أكثر 10 كلمات تكراراً في هذه الدخيرة اللغوية؟",
        description="Identify the dominant lexical content of the corpus.",
    ),
    QueryTemplate(
        id="freq-top-content",
        category="frequency",
        label_en="Top 20 content words (excluding function words)",
        label_ar="أفضل 20 كلمة معجمية (باستثناء أدوات المعنى)",
        query_en="What are the top 20 content words (nouns, verbs, adjectives, adverbs) by frequency, excluding function words?",
        query_ar="ما هي أفضل 20 كلمة معجمية (أسماء، أفعال، صفات، ظروف) من حيث التكرار، باستثناء أدوات المعنى؟",
        description="Filter out function words to surface the topical vocabulary.",
    ),
    QueryTemplate(
        id="freq-vs-reference",
        category="frequency",
        label_en="Compare top-100 here vs. a reference",
        label_ar="قارن أفضل 100 كلمة هنا بالدخيرة المرجعية",
        query_en="How does the top-100 frequency list in this corpus compare to general written English? Which words are over-represented?",
        query_ar="كيف تقارن قائمة أفضل 100 كلمة تكراراً في هذه الدخيرة بالإنجليزية المكتوبة العامة؟ ما الكلمات المفرطة التمثيل؟",
        requires_reference=True,
    ),

    # --- Collocation ---
    QueryTemplate(
        id="colloc-strong",
        category="collocation",
        label_en="Strongest collocates of a node word",
        label_ar="أقوى المتلازمات اللفظية لكلمة محور",
        query_en="What are the strongest collocates of '{node}' within a ±5 token window, ranked by log-likelihood?",
        query_ar="ما هي أقوى المتلازمات اللفظية لكلمة '{node}' ضمن نافذة ±5 رموز، مرتبة حسب الاحتمالية اللوغاريتمية؟",
        description="Discover words that habitually co-occur with a node.",
    ),
    QueryTemplate(
        id="colloc-mi-vs-tscore",
        category="collocation",
        label_en="Compare MI vs. T-score collocates",
        label_ar="قارن متلازمات MI بـ T-score",
        query_en="For the node '{node}', how do the top-10 MI-ranked collocates differ from the top-10 T-score-ranked collocates? What does the difference tell us?",
        query_ar="بالنسبة لكلمة '{node}'، كيف تختلف أفضل 10 متلازمات وفق MI عن أفضل 10 وفق T-score؟ ماذا يخبرنا الفرق؟",
        description="MI highlights exclusive associations; T-score highlights frequent ones.",
    ),

    # --- Keyness ---
    QueryTemplate(
        id="keyness-top-positive",
        category="keyness",
        label_en="Top positive keywords vs. reference",
        label_ar="أهم الكلمات المفتاحية الإيجابية مقابل المرجع",
        query_en="What are the top 20 positive keywords in this corpus compared to the reference, with both log-likelihood and Log Ratio reported?",
        query_ar="ما هي أهم 20 كلمة مفتاحية إيجابية في هذه الدخيرة مقارنة بالمرجع، مع الإبلاغ عن الاحتمالية اللوغاريتمية و Log Ratio؟",
        requires_reference=True,
        description="Identify words that distinguish this corpus from the reference.",
    ),
    QueryTemplate(
        id="keyness-negative",
        category="keyness",
        label_en="Top negative keywords (under-represented)",
        label_ar="أهم الكلمات المفتاحية السلبية (ناقصة التمثيل)",
        query_en="What are the top 20 negative keywords — words significantly under-represented in this corpus compared to the reference?",
        query_ar="ما هي أهم 20 كلمة مفتاحية سلبية — كلمات ناقصة التمثيل بشكل معنوي في هذه الدخيرة مقارنة بالمرجع؟",
        requires_reference=True,
        description="Identify what this corpus avoids relative to the reference.",
    ),

    # --- Concordance ---
    QueryTemplate(
        id="concord-browse",
        category="concordance",
        label_en="Browse all occurrences of a word",
        label_ar="تصفح جميع تكرارات كلمة",
        query_en="Show me all occurrences of '{node}' with ±5 tokens of context, sorted by document.",
        query_ar="اعرض لي جميع تكرارات '{node}' مع ±5 رموز من السياق، مرتبة حسب الوثيقة.",
    ),
    QueryTemplate(
        id="concord-pos-pattern",
        category="concordance",
        label_en="Find a POS pattern (e.g. ADJ + NOUN)",
        label_ar="ابحث عن نمط صرفي (مثل صفة + اسم)",
        query_en="Find all instances where an adjective is immediately followed by a noun, and show the top 20 most frequent ADJ+NOUN pairs.",
        query_ar="ابحث عن جميع الحالات التي تتبع فيها صفةٌ اسماً مباشرة، واعرض أفضل 20 زوجاً متكرراً من صفة+اسم.",
    ),

    # --- Dispersion ---
    QueryTemplate(
        id="dispersion-even",
        category="dispersion",
        label_en="How evenly is 'the' distributed?",
        label_ar="ما مدى تساوي توزيع 'the'؟",
        query_en="How evenly is 'the' distributed across the documents in this corpus? Report Juilland's D and Gries' DP.",
        query_ar="ما مدى تساوي توزيع 'the' عبر الوثائق في هذه الدخيرة؟ أبلغ عن Juilland's D و Gries' DP.",
    ),

    # --- N-grams ---
    QueryTemplate(
        id="ngrams-top-bigrams",
        category="ngrams",
        label_en="Top 20 most frequent bigrams",
        label_ar="أفضل 20 ثنائية لفظية متكررة",
        query_en="What are the top 20 most frequent 2-word sequences (bigrams) in this corpus, excluding bigrams that span sentence boundaries?",
        query_ar="ما هي أفضل 20 تسلسل ثنائي الكلمات (bigrams) تكراراً في هذه الدخيرة، باستثناء تلك التي تعبر حدود الجمل؟",
    ),

    # --- POS ---
    QueryTemplate(
        id="pos-distribution",
        category="pos",
        label_en="Overall POS distribution",
        label_ar="التوزيع الصرفي العام",
        query_en="What is the overall POS tag distribution in this corpus? Show percentages for each UPOS category.",
        query_ar="ما هو التوزيع الصرفي العام في هذه الدخيرة؟ اعرض النسب المئوية لكل فئة UPOS.",
    ),

    # --- Compare ---
    QueryTemplate(
        id="compare-two-corpora",
        category="compare",
        label_en="Compare this corpus to another",
        label_ar="قارن هذه الدخيرة بأخرى",
        query_en="Compare this corpus against the reference corpus side-by-side for the word '{node}'. How do the contexts differ?",
        query_ar="قارن هذه الدخيرة بالدخيرة المرجعية جنباً إلى جنب لكلمة '{node}'. كيف تختلف السياقات؟",
        requires_reference=True,
    ),

    # --- Methodology ---
    QueryTemplate(
        id="method-summary",
        category="methodology",
        label_en="Summarise the corpus for my Methods section",
        label_ar="لخّص الدخيرة لقسم المنهجية",
        query_en="Summarise this corpus for my Methods section: number of tokens, types, documents, TTR, and the annotation pipeline used.",
        query_ar="لخّص هذه الدخيرة لقسم المنهجية: عدد الرموز، الأنواع، الوثائق، TTR، وخط المعالجة اللغوية المستخدم.",
        requires_corpus=True,
    ),

    # --- Explore (open-ended) ---
    QueryTemplate(
        id="explore-unusual",
        category="explore",
        label_en="What's unusual about this corpus?",
        label_ar="ما الذي غير معتاد في هذه الدخيرة؟",
        query_en="Based on the frequency and keyness results, what is unusual or noteworthy about this corpus compared to typical written text?",
        query_ar="بناءً على نتائج التكرار وأهمية الكلمات، ما الذي غير معتاد أو جدير بالملاحظة في هذه الدخيرة مقارنة بالنص المكتوب النموذجي؟",
        requires_reference=True,
    ),
]


# --------------------------------------------------------------------------- #
# Dynamic query generation
# --------------------------------------------------------------------------- #


DYNAMIC_SYSTEM_PROMPT = """You are a corpus-linguistics research assistant. Given a summary of a corpus and (optionally) the user's most recent analysis results, suggest 3 to 5 follow-up research questions that:

1. Build on what the user has already found — do not repeat their current analysis verbatim.
2. Leverage the corpus's unique characteristics (size, language, genre, register).
3. Are answerable by the available grounded tools: search_concordance, get_frequency, compute_collocations, compute_keyness, get_dispersion.
4. Are concrete enough that the user can paste them directly into the chat (no placeholders the user has to fill in).
5. Are written in {language}.

Return STRICT JSON: an array of objects with keys "query" (string), "rationale" (string, 1 sentence), and "category" (one of: frequency, collocation, keyness, concordance, dispersion, ngrams, pos, compare, explore, methodology).

Do not include any text outside the JSON array.
"""


@dataclass
class DynamicSuggestion:
    query: str
    rationale: str
    category: str


async def _build_corpus_summary(session: AsyncSession, corpus_id: str) -> dict[str, Any]:
    """Collect a compact statistical summary for the LLM prompt."""
    from stats.service import _corpus_size, _latest_version_id, compute_frequency
    from storage.models import Corpus

    corpus = await session.get(Corpus, corpus_id)
    if corpus is None:
        return {}

    summary: dict[str, Any] = {
        "name": corpus.name,
        "language": corpus.language,
        "genre": corpus.genre,
        "stats": corpus.stats or {},
    }

    # Top-10 words — cheap + gives the LLM concrete lexical hooks.
    try:
        vid = await _latest_version_id(session, corpus_id)
        if vid:
            summary["N"] = await _corpus_size(session, vid)
            freq = await compute_frequency(session, corpus_id, unit="word", min_freq=2, limit=10)
            summary["top_words"] = [r["item"] for r in freq.rows]
    except Exception as e:
        log.warning("corpus_summary_freq_failed", error=str(e))

    return summary


def _parse_dynamic_response(text: str, *, language: str) -> list[DynamicSuggestion]:
    """Parse the LLM's JSON-array response. Tolerates minor JSON issues."""
    text = text.strip()
    # Strip ```json fences if the model wrapped the output.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        # Last-ditch: find the first '[' and last ']' and try again.
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            log.warning("dynamic_suggestions_parse_failed", text_preview=text[:200])
            return []
        try:
            items = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return []

    out: list[DynamicSuggestion] = []
    if not isinstance(items, list):
        return []
    for item in items[:8]:  # cap at 8 to keep the UI sane
        if not isinstance(item, dict):
            continue
        query = str(item.get("query", "")).strip()
        if not query:
            continue
        out.append(DynamicSuggestion(
            query=query,
            rationale=str(item.get("rationale", ""))[:240],
            category=str(item.get("category", "explore")),
        ))
    return out


async def generate_dynamic_queries(
    session: AsyncSession,
    *,
    corpus_id: str | None,
    provider,  # ModelProvider — duck-typed
    model: str | None,
    recent_analysis: dict[str, Any] | None = None,
    language: str = "en",
) -> list[DynamicSuggestion]:
    """Generate LLM-powered follow-up research questions.

    Returns an empty list (not an error) when:
      - no corpus is loaded
      - the corpus has no tokens yet
      - the provider is unreachable
      - the LLM returns unparseable output

    The caller (API endpoint) merges these with the pre-fabricated list.
    """
    if not corpus_id:
        return []

    summary = await _build_corpus_summary(session, corpus_id)
    if not summary or not summary.get("stats"):
        return []

    prompt = DYNAMIC_SYSTEM_PROMPT.format(language=language)
    user_msg = (
        f"Corpus summary:\n```json\n{json.dumps(summary, indent=2, ensure_ascii=False)}\n```\n\n"
    )
    if recent_analysis:
        user_msg += (
            f"The user just ran this analysis:\n```json\n"
            f"{json.dumps(recent_analysis, indent=2, ensure_ascii=False)}\n```\n\n"
        )
    user_msg += "Suggest 3-5 follow-up research questions as a JSON array."

    from ai.providers import Message
    messages = [
        Message(role="system", content=prompt),
        Message(role="user", content=user_msg),
    ]

    try:
        # Issue 2b: use chat_json() so the provider sets the JSON-format flag.
        resp = await provider.chat_json(messages, model=model, temperature=0.4)
    except Exception as e:
        log.warning("dynamic_suggestions_llm_failed", error=str(e))
        return []

    return _parse_dynamic_response(resp.content, language=language)


# --------------------------------------------------------------------------- #
# Public helpers
# --------------------------------------------------------------------------- #


def list_prefabricated(*, language: str = "en") -> list[dict[str, Any]]:
    """Return the pre-fabricated queries in the requested language."""
    out: list[dict[str, Any]] = []
    for q in PREFABRICATED_QUERIES:
        out.append({
            "id": q.id,
            "category": q.category,
            "label": q.label_en if language == "en" else q.label_ar,
            "query": q.query_en if language == "en" else q.query_ar,
            "requires_corpus": q.requires_corpus,
            "requires_reference": q.requires_reference,
            "description": q.description,
            "source": "prefabricated",
        })
    return out


def has_reference_for_language(language: str) -> bool:
    """Check whether at least one bundled reference is installed for ``language``.

    Used by the API endpoint to mark pre-fabricated queries with
    ``requires_reference=True`` as available or greyed-out.
    """
    try:
        from reference_corpus import get_manager
        mgr = get_manager()
        return any(
            entry.language == language
            for entry in mgr.manifest.list_entries()
        )
    except Exception:
        return False
