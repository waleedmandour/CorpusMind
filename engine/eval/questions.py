"""Grounding question bank (80 questions) for the fixed snapshot corpus.

Every question pins:
- the exact tool calls whose frozen outputs constitute the gold,
- a gold spec resolved at BUILD time by ``build_gold.py`` (never re-derived
  from a live run), and
- the trap class where applicable.

Gold spec kinds
---------------
N(path, label, tol)   numeric value (default tolerance: exact for ints,
                      1e-6 relative for floats)
S(path, label)        string value — scorer checks the answer quotes it
C(path, label)        count of a returned list
D(path, label)        distinct count of a returned list (e.g. documents)
L(path, label)        list of numbers — every value must appear in the answer
A(path, key, label)   argmax key of a dict-of-stats (returns the key name)
X(path, label)        expected-absent marker (resolver must FAIL to find it)
TZ(path, label)       trap: path must resolve to 0 at build (zero-match)
TE                    trap: the tool call itself must fail (CQL syntax error)
TN                    trap: no tool exists — the honest answer is "cannot be
                      grounded"; quoting any number is a failure

Path grammar: ``t<tool-index>.<dotted.path>`` with optional ``[key=value]``
row filters, ``[0]`` numeric indices, and bracketed literal keys for dotted
names (``categories.[interactional.hedges].freq``).
"""

from __future__ import annotations

from typing import Any


def _g(kind: str, path: str, label: str, **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "path": path, "label": label, **extra}


def N(path: str, label: str, tol: float = 1e-6) -> dict[str, Any]:
    return _g("number", path, label, tol=tol)


def S(path: str, label: str) -> dict[str, Any]:
    return _g("string", path, label)


def C(path: str, label: str) -> dict[str, Any]:
    return _g("count", path, label)


def D(path: str, label: str) -> dict[str, Any]:
    return _g("distinct", path, label)


def L(path: str, label: str) -> dict[str, Any]:
    return _g("list_each", path, label)


def A(path: str, key: str, label: str) -> dict[str, Any]:
    return _g("argmax", path, label, argmax=key)


def P(path: str, label: str) -> dict[str, Any]:
    """Expected-PRESENT marker: resolver must FIND a matching row."""
    return _g("present", path, label)


def X(path: str, label: str) -> dict[str, Any]:
    return _g("absent", path, label)


def TZ(path: str, label: str) -> dict[str, Any]:
    return _g("trap_zero", path, label)


TE: dict[str, Any] = {"kind": "trap_error"}
TN: dict[str, Any] = {"kind": "trap_no_tool"}


def T(name: str, **args: Any) -> dict[str, Any]:
    """One canonical tool call (args may use symbolic corpora and @file texts)."""
    return {"name": name, "args": args}


def Q(
    qid: str,
    category: str,
    language: str,
    corpus: str,
    question: str,
    tools: list[dict[str, Any]],
    gold: list[dict[str, Any]],
    *,
    trap: bool = False,
) -> dict[str, Any]:
    return {
        "id": qid,
        "category": category,
        "language": language,
        "corpus": corpus,
        "question": question,
        "tools": tools,
        "gold_spec": gold,
        "trap": trap,
    }


QUESTION_BANK: list[dict[str, Any]] = [
    # ------------------------------------------------------------------ #
    # corpus_stats (6)
    # ------------------------------------------------------------------ #
    Q("G-001", "corpus_stats", "en", "C1",
      "How many documents, tokens, distinct word types, and sentences does this corpus contain?",
      [T("get_corpus_overview", corpus="C1")],
      [N("t0.text_side.document_count", "documents"),
       N("t0.text_side.token_count", "tokens"),
       N("t0.text_side.type_count", "types"),
       N("t0.text_side.sentence_count", "sentences")]),
    Q("G-002", "corpus_stats", "ar", "C4",
      "كم مستنداً وكم كلمة وكم نوعاً وكم جملة في هذا المحتوى؟",
      [T("get_corpus_overview", corpus="C4")],
      [N("t0.text_side.document_count", "documents"),
       N("t0.text_side.token_count", "tokens"),
       N("t0.text_side.type_count", "types"),
       N("t0.text_side.sentence_count", "sentences")]),
    Q("G-003", "corpus_stats", "en", "C1",
      "What are the total tokens and total types, and how often does the most frequent word occur?",
      [T("get_frequency", corpus="C1", unit="word", limit=5)],
      [N("t0.total_tokens", "total tokens"),
       N("t0.total_types", "total types"),
       N("t0.top_items[0].freq", "top word freq"),
       S("t0.top_items[0].item", "top word")]),
    Q("G-004", "diversity", "en", "C1",
      "What is the type-token ratio (TTR) of this corpus?",
      [],
      [TN]),
    Q("G-005", "corpus_stats", "ar", "C4",
      "كم عدد الكلمات والأنواع المختلفة في هذا المحتوى؟",
      [T("get_frequency", corpus="C4", unit="word", limit=1)],
      [N("t0.total_tokens", "total tokens"),
       N("t0.total_types", "total types")]),
    Q("G-006", "corpus_stats", "en", "C2",
      "For the learner corpus: how many tokens and how many types?",
      [T("get_frequency", corpus="C2", unit="word", limit=1)],
      [N("t0.total_tokens", "tokens"), N("t0.total_types", "types")]),

    # ------------------------------------------------------------------ #
    # keyness (10) — target C2 (learner) vs reference C3 (press)
    # ------------------------------------------------------------------ #
    Q("G-007", "keyness", "en", "C2",
      "Which word is the single strongest positive keyword of this corpus compared with the press corpus, and how many tokens does each corpus have? Use the reference corpus ID given in the context.",
      [T("compute_keyness", corpus="C2", reference="C3", limit=10)],
      [S("t0.positive_keywords[0].term", "top positive keyword"),
       N("t0.N1", "N1"), N("t0.N2", "N2")]),
    Q("G-008", "keyness", "en", "C2",
      "How many positive keywords and how many negative keywords does the keyness comparison report (vs the press corpus)?",
      [T("compute_keyness", corpus="C2", reference="C3", limit=10)],
      [C("t0.positive_keywords", "positive keywords"),
       C("t0.negative_keywords", "negative keywords")]),
    Q("G-009", "keyness", "en", "C2",
      "For the word 'goal': what are its log ratio and percent difference (%DIFF) in the keyness table vs the press corpus?",
      [T("compute_keyness", corpus="C2", reference="C3", limit=50)],
      [N("t0.positive_keywords[term=goal].log_ratio", "log_ratio"),
       N("t0.positive_keywords[term=goal].pct_diff", "pct_diff")]),
    Q("G-010", "keyness", "en", "C2",
      "For 'goal': what are the exact p-value (p_ll) and the Benjamini-Hochberg q-value, and is it significant at q < 0.05?",
      [T("compute_keyness", corpus="C2", reference="C3", limit=50)],
      [N("t0.positive_keywords[term=goal].p_ll", "p_ll"),
       N("t0.positive_keywords[term=goal].q_bh", "q_bh")]),
    Q("G-011", "keyness", "en", "C2",
      "What is the strongest negative keyword of the learner corpus vs the press corpus, and what is its log ratio?",
      [T("compute_keyness", corpus="C2", reference="C3", limit=10)],
      [S("t0.negative_keywords[0].term", "top negative keyword"),
       N("t0.negative_keywords[0].log_ratio", "its log_ratio")]),
    Q("G-012", "keyness", "en", "C3",
      "Comparing this press corpus with the bundled BE06 written-English reference, what is the top positive keyword and what is N1?",
      [],
      [TN]),
    Q("G-013", "keyness", "en", "C2",
      "Is the word 'the' listed as a positive keyword of the learner corpus? If it appears in the table, what is its log ratio?",
      [T("compute_keyness", corpus="C2", reference="C3", limit=50)],
      [X("t0.positive_keywords[term=the]", "row for 'the'")]),
    Q("G-014", "keyness", "en", "C2",
      "What is the third word listed among the positive keywords of the learner corpus vs the press corpus?",
      [T("compute_keyness", corpus="C2", reference="C3", limit=10)],
      [S("t0.positive_keywords[2].term", "third positive keyword")]),
    Q("G-015", "keyness", "en", "C2",
      "Which is larger, the target or the reference token count, and what are the two counts (N1 and N2)?",
      [T("compute_keyness", corpus="C2", reference="C3", limit=1)],
      [N("t0.N1", "N1"), N("t0.N2", "N2")]),
    Q("G-016", "keyness", "en", "C2",
      "Is the word 'my' among the positive keywords of the learner corpus vs the press corpus?",
      [T("compute_keyness", corpus="C2", reference="C3", limit=100)],
      [P("t0.positive_keywords[term=my]", "row for 'my'")]),

    # ------------------------------------------------------------------ #
    # dispersion (7) — parts are the documents of C1
    # ------------------------------------------------------------------ #
    Q("G-017", "dispersion", "en", "C1",
      "What are Gries' DP and Juilland's D for the word 'algorithm' across the documents?",
      [T("get_dispersion", corpus="C1", term="algorithm")],
      [N("t0.gries_dp", "DP"), N("t0.juillands_d", "Juilland's D")]),
    Q("G-018", "dispersion", "en", "C1",
      "In which parts does 'algorithm' occur, and how many times in each part?",
      [T("get_dispersion", corpus="C1", term="algorithm")],
      [L("t0.per_part_freqs", "per-part frequencies")]),
    Q("G-019", "dispersion", "en", "C1",
      "What is the DP-norm of the word 'goal', and what is its range percent across documents?",
      [],
      [TN]),
    Q("G-020", "dispersion", "en", "C1",
      "What is Juilland's D for 'the'?",
      [T("get_dispersion", corpus="C1", term="the")],
      [N("t0.juillands_d", "Juilland's D")]),
    Q("G-021", "dispersion", "en", "C1",
      "The word 'theatre' occurs only once in the whole corpus. What DP does the engine report for it?",
      [T("get_dispersion", corpus="C1", term="theatre")],
      [N("t0.gries_dp", "DP")]),
    Q("G-022", "dispersion", "en", "C1",
      "What is DP for 'goal' at word level and at lemma level?",
      [T("get_dispersion", corpus="C1", term="goal", level="word"),
       T("get_dispersion", corpus="C1", term="goal", level="lemma")],
      [N("t0.gries_dp", "DP word"), N("t1.gries_dp", "DP lemma")]),
    Q("G-023", "dispersion", "en", "C1",
      "For 'council': how often does it occur in each part (document)?",
      [T("get_dispersion", corpus="C1", term="council")],
      [L("t0.per_part_freqs", "per-part frequencies")]),

    # ------------------------------------------------------------------ #
    # lexical diversity (6)
    # ------------------------------------------------------------------ #
    Q("G-024", "diversity", "en", "C1",
      "What are the MATTR and MTLD values for this corpus?",
      [],
      [TN]),
    Q("G-025", "diversity", "en", "C1",
      "What is Guiraud's Root TTR for this corpus?",
      [],
      [TN]),
    Q("G-026", "diversity", "en", "C2",
      "What is the TTR of the learner corpus?",
      [],
      [TN]),
    Q("G-027", "diversity", "ar", "C4",
      "ما قيمة STTR لهذا المحتوى؟",
      [T("get_frequency", corpus="C4", unit="word", limit=1)],
      [N("t0.sttr", "STTR")]),
    Q("G-028", "diversity", "en", "C2",
      "What is the MTLD of the learner corpus?",
      [],
      [TN]),
    Q("G-029", "diversity", "en", "C2",
      "What is the STTR of the learner corpus?",
      [T("get_frequency", corpus="C2", unit="word", limit=1)],
      [N("t0.sttr", "STTR")]),

    # ------------------------------------------------------------------ #
    # collocations (6) — same-sentence by construction
    # ------------------------------------------------------------------ #
    Q("G-030", "collocation", "en", "C1",
      "What is the strongest collocate of 'park' by mutual information (window 5), what is its MI score, and how many times do they co-occur (O)?",
      [T("compute_collocations", corpus="C1", node="park", window=5, min_freq=1)],
      [S("t0.top_collocates[0].collocate", "top collocate"),
       N("t0.top_collocates[0].mi", "MI"), N("t0.top_collocates[0].O", "O")]),
    Q("G-031", "collocation", "en", "C1",
      "For the node 'river', what is the Log-Dice score of the top-ranked collocate?",
      [T("compute_collocations", corpus="C1", node="river", window=5, min_freq=1)],
      [N("t0.top_collocates[0].log_dice", "log_dice")]),
    Q("G-032", "collocation", "en", "C1",
      "How many distinct collocates does 'goal' have within a window of 5?",
      [T("compute_collocations", corpus="C1", node="goal", window=5, min_freq=1)],
      [C("t0.top_collocates", "number of collocates")]),
    Q("G-033", "collocation", "en", "C1",
      "What is the t-score of the top collocate of 'council', and how many times do they co-occur?",
      [T("compute_collocations", corpus="C1", node="council", window=5, min_freq=1)],
      [N("t0.top_collocates[0].t_score", "t-score"), N("t0.top_collocates[0].O", "O")]),
    Q("G-034", "collocation", "en", "C1",
      "For the top collocate of 'park': what are fx (collocate frequency) and fy, and what is N?",
      [T("compute_collocations", corpus="C1", node="park", window=5, min_freq=1)],
      [N("t0.top_collocates[0].fx", "fx"), N("t0.top_collocates[0].fy", "fy"), N("t0.top_collocates[0].N", "N")]),
    Q("G-035", "collocation", "en", "C1",
      "How many collocates does 'park' have with window 2, and how many with window 5?",
      [T("compute_collocations", corpus="C1", node="park", window=2, min_freq=1),
       T("compute_collocations", corpus="C1", node="park", window=5, min_freq=1)],
      [C("t0.top_collocates", "collocates window 2"),
       C("t1.top_collocates", "collocates window 5")]),

    # ------------------------------------------------------------------ #
    # n-grams (4)
    # ------------------------------------------------------------------ #
    Q("G-036", "ngrams", "en", "C1",
      "What is the most frequent 3-gram in this corpus, and how often does it occur?",
      [T("get_ngrams", corpus="C1", n=3, min_freq=2, min_range=1, limit=5)],
      [S("t0.top_ngrams[0].ngram", "top 3-gram"), N("t0.top_ngrams[0].freq", "freq")]),
    Q("G-037", "ngrams", "en", "C1",
      "What is the most frequent 2-gram, and what is its frequency?",
      [T("get_ngrams", corpus="C1", n=2, min_freq=2, min_range=1, limit=5)],
      [S("t0.top_ngrams[0].ngram", "top 2-gram"), N("t0.top_ngrams[0].freq", "freq")]),
    Q("G-038", "ngrams", "en", "C1",
      "How many different 2-grams occur in at least two different documents (range at least 2)?",
      [T("get_ngrams", corpus="C1", n=2, min_freq=2, min_range=2, limit=50)],
      [C("t0.top_ngrams", "2-grams with range >= 2")]),
    Q("G-039", "ngrams", "en", "C1",
      "What frequency does the engine report for the 2-gram 'the park' (min frequency 2)?",
      [T("get_ngrams", corpus="C1", n=2, min_freq=2, min_range=1, limit=100)],
      [N("t0.top_ngrams[ngram=the park].freq", "freq of 'the park'")]),

    # ------------------------------------------------------------------ #
    # KWIC / concordance (7)
    # ------------------------------------------------------------------ #
    Q("G-040", "kwic", "en", "C1",
      "How many hits does 'park' have, and what is the line_id of the first hit?",
      [T("search_concordance", corpus="C1", query="park", window=5, limit=10)],
      [N("t0.total_matches", "total hits"), S("t0.lines[0].line_id", "first line_id")]),
    Q("G-041", "kwic", "en", "C1",
      "How many hits does 'council' have, and in how many different documents do they occur?",
      [T("search_concordance", corpus="C1", query="council", window=5, limit=20)],
      [N("t0.total_matches", "total hits"),
       D("t0.lines[*].document", "distinct documents")]),
    Q("G-042", "kwic", "en", "C2",
      "Compare the lemma 'go' with the exact word form 'go' in the learner corpus: how many hits does each have?",
      [T("search_concordance", corpus="C2", query="go", level="lemma", window=3, limit=20),
       T("search_concordance", corpus="C2", query="go", level="word", window=3, limit=20)],
      [N("t0.total_matches", "lemma hits"), N("t1.total_matches", "word hits")]),
    Q("G-043", "kwic", "en", "C1",
      "How many hits does 'council' have in the press subcorpus, and how many in the full corpus? Use the corpus IDs given in the context.",
      [T("search_concordance", corpus="C3", query="council", window=3, limit=20),
       T("search_concordance", corpus="C1", query="council", window=3, limit=20)],
      [N("t0.total_matches", "press hits"), N("t1.total_matches", "full-corpus hits")]),
    Q("G-044", "kwic", "ar", "C4",
      "كم نتيجة لكلمة المشروع في هذا المحتوى، وما معرّف أول نتيجة (line_id)؟",
      [T("search_concordance", corpus="C4", query="المشروع", window=5, limit=10)],
      [N("t0.total_matches", "total hits"), S("t0.lines[0].line_id", "first line_id")]),
    Q("G-045", "kwic", "en", "C2",
      "What is the line_id of the second hit for 'goal' in the learner corpus, and how many hits are there in total?",
      [T("search_concordance", corpus="C2", query="goal", window=3, limit=20)],
      [S("t0.lines[1].line_id", "second line_id"), N("t0.total_matches", "total")]),
    Q("G-046", "kwic", "en", "C1",
      "How many hits does 'riverfront' have, and how many hits does 'river' have?",
      [T("search_concordance", corpus="C1", query="riverfront", window=3, limit=10),
       T("search_concordance", corpus="C1", query="river", window=3, limit=10)],
      [N("t0.total_matches", "'riverfront' hits"), N("t1.total_matches", "'river' hits")]),

    # ------------------------------------------------------------------ #
    # CQL (6)
    # ------------------------------------------------------------------ #
    Q("G-047", "cql", "en", "C1",
      "Using CQL, how many hits does the query [lemma=\"algorithm\"] return?",
      [T("search_cql", corpus="C1", query='[lemma="algorithm"]', window=3)],
      [N("t0.total", "total hits")]),
    Q("G-048", "cql", "en", "C1",
      "How many case-insensitive CQL hits does the query \"park\" %c return?",
      [T("search_cql", corpus="C1", query='"park" %c', window=3)],
      [N("t0.total", "total hits")]),
    Q("G-049", "cql", "en", "C1",
      "How many hits does the CQL query [lemma=\"new\"] []{0,2} \"park\" return?",
      [T("search_cql", corpus="C1", query='[lemma="new"] []{0,2} "park"', window=3)],
      [N("t0.total", "total hits")]),
    Q("G-050", "cql", "en", "C1",
      "For the word 'council': does the hit count change between the CQL scope \"within sentence\" and \"within document\"? Give both totals.",
      [T("search_cql", corpus="C1", query='"council" within sentence', window=3),
       T("search_cql", corpus="C1", query='"council" within document', window=3)],
      [N("t0.total", "within sentence"), N("t1.total", "within document")]),
    Q("G-051", "cql", "en", "C1",
      "Run the CQL query [[[broken and tell me how many hits it returns.",
      [T("search_cql", corpus="C1", query="[[[broken", window=3)],
      [TE]),
    Q("G-052", "cql", "en", "C1",
      "How many hits does the CQL query \"study\" []{0,2} \"science\" return?",
      [T("search_cql", corpus="C1", query='"study" []{0,2} "science"', window=3)],
      [N("t0.total", "total hits")]),

    # ------------------------------------------------------------------ #
    # sentiment (5)
    # ------------------------------------------------------------------ #
    Q("G-053", "sentiment", "en", "C1",
      "How many sentences of this corpus are classified positive, negative, and neutral?",
      [T("sentiment", corpus="C1")],
      [N("t0.positive", "positive"), N("t0.negative", "negative"),
       N("t0.neutral", "neutral")]),
    Q("G-054", "sentiment", "en", "C1",
      "What is the average sentiment score of the corpus, and how many sentences were analysed?",
      [T("sentiment", corpus="C1")],
      [N("t0.avg_score", "avg score"), N("t0.total_sentences", "sentences")]),
    Q("G-055", "sentiment", "en", "C6",
      "For the parallel English corpus: how many sentences are positive, and what is the average sentiment score?",
      [T("sentiment", corpus="C6")],
      [N("t0.positive", "positive"), N("t0.avg_score", "avg score")]),
    Q("G-056", "sentiment", "ar", "C4",
      "كم جملة إيجابية وسلبية ومحايدة في هذا المحتوى؟",
      [T("sentiment", corpus="C4")],
      [N("t0.positive", "positive"), N("t0.negative", "negative"),
       N("t0.neutral", "neutral")]),
    Q("G-057", "sentiment", "en", "C2",
      "For the learner essay corpus: how many positive, negative, and neutral sentences are there?",
      [T("sentiment", corpus="C2")],
      [N("t0.positive", "positive"), N("t0.negative", "negative"),
       N("t0.neutral", "neutral")]),

    # ------------------------------------------------------------------ #
    # Arabic register (5) — stateless tools, text passed directly
    # ------------------------------------------------------------------ #
    Q("G-058", "register", "ar", "C4",
      "تصنيف السجلات (فصحى كلاسيكية، فصحى عصرية، لهجة) لنصٍّ معيّن: ما توزيع النص الآتي؟ «أعلنت الوزارة عن مشروع جديد لتطوير التعليم الرقمي في المدارس الحكومية.»",
      [T("arabic_register", text="أعلنت الوزارة عن مشروع جديد لتطوير التعليم الرقمي في المدارس الحكومية.")],
      [N("t0.register_distribution.classical", "classical"),
       N("t0.register_distribution.msa", "msa"),
       N("t0.register_distribution.dialectal", "dialectal")]),
    Q("G-059", "register", "ar", "C4",
      "ما التصنيف السائد لنص «كان الملوك يجتمعون في هذا الموضع يتفاوضون في شؤون الرعية. وقد قال الحكيم: إنّ عدل السلطان أصل عمارة البلاد»؟",
      [T("arabic_register", text="كان الملوك يجتمعون في هذا الموضع يتفاوضون في شؤون الرعية. وقد قال الحكيم: إنّ عدل السلطان أصل عمارة البلاد")],
      [N("t0.register_distribution.classical", "classical"),
       N("t0.register_distribution.msa", "msa"),
       N("t0.register_distribution.dialectal", "dialectal")]),
    Q("G-060", "register", "ar", "C4",
      "للهجة: ما توزيع السجلات لنص «ليش ما رح تيجي معنا على البحرية؟ الشو كان حلو كتير مبارح»؟",
      [T("arabic_register", text="ليش ما رح تيجي معنا على البحرية؟ الشو كان حلو كتير مبارح")],
      [N("t0.register_distribution.classical", "classical"),
       N("t0.register_distribution.msa", "msa"),
       N("t0.register_distribution.dialectal", "dialectal")]),
    Q("G-061", "register", "ar", "C4",
      "نص بلا علامات ترقيم: ما توزيع السجلات لنص «ذهب الطلاب إلى المكتبة في الصباح الباكر قرأوا القصة ثم كتبوا ملخصاً قصيراً عنها»؟",
      [T("arabic_register", text="ذهب الطلاب إلى المكتبة في الصباح الباكر قرأوا القصة ثم كتبوا ملخصاً قصيراً عنها")],
      [N("t0.register_distribution.classical", "classical"),
       N("t0.register_distribution.msa", "msa"),
       N("t0.register_distribution.dialectal", "dialectal")]),
    Q("G-062", "register", "ar", "C4",
      "ما التصنيف السائد لنص «سافر التاجر العجوز إلى الساحل كل ربيع.»؟",
      [T("arabic_register", text="سافر التاجر العجوز إلى الساحل كل ربيع.")],
      [N("t0.register_distribution.classical", "classical"),
       N("t0.register_distribution.msa", "msa"),
       N("t0.register_distribution.dialectal", "dialectal")]),

    # ------------------------------------------------------------------ #
    # Arabic morphology / dialect (4)
    # ------------------------------------------------------------------ #
    Q("G-063", "arabic_tools", "ar", "C4",
      "ما تصنيف اللهجة لهذا النص؟ «ليش ما رح تيجي معنا على البحرية؟ الشو كان حلو كتير مبارح، وهويك الجو منعش.»",
      [T("arabic_dialect_id", text="ليش ما رح تيجي معنا على البحرية؟ الشو كان حلو كتير مبارح، وهويك الجو منعش.")],
      [N("t0.dialect_distribution.dialect_distribution.egy", "egy"),
       N("t0.dialect_distribution.dialect_distribution.glf", "glf"),
       N("t0.dialect_distribution.dialect_distribution.lev", "lev")]),
    Q("G-064", "arabic_tools", "ar", "C4",
      "ما تصنيف اللهجة لنص «أعلنت الوزارة عن مشروع جديد لتطوير التعليم الرقمي في المدارس الحكومية.»؟",
      [T("arabic_dialect_id", text="أعلنت الوزارة عن مشروع جديد لتطوير التعليم الرقمي في المدارس الحكومية.")],
      [N("t0.dialect_distribution.dialect_distribution.msa", "msa"),
       N("t0.dialect_distribution.dialect_distribution.egy", "egy"),
       N("t0.dialect_distribution.dialect_distribution.glf", "glf"),
       N("t0.dialect_distribution.dialect_distribution.lev", "lev")]),
    Q("G-065", "arabic_tools", "ar", "C4",
      "استخرج جذور الكلمات في العبارة: «الطلاب يقرأون القصة» — كم جذاذة (root) مختلفة يعيدها المحرك؟",
      [T("arabic_roots", text="الطلاب يقرأون القصة")],
      [C("t0.roots", "distinct roots")]),
    Q("G-066", "arabic_tools", "ar", "C4",
      "كم رمزاً (token) يحلل محرك التشكيل للنص: «قال الوزير إن المشروع سيبدأ»؟ وما الجذر الأول المُعاد؟",
      [T("arabic_morphology", text="قال الوزير إن المشروع سيبدأ", dialect="msa")],
      [N("t0.token_count", "token count"), S("t0.top_tokens[0].root", "first root")]),

    # ------------------------------------------------------------------ #
    # discourse (3)
    # ------------------------------------------------------------------ #
    Q("G-067", "discourse", "en", "C1",
      "Using the Hyland (2005) metadiscourse analysis, how many tokens does the corpus have, and which metadiscourse category is the most frequent?",
      [T("discourse_analysis", corpus="C1")],
      [N("t0.total_tokens", "total tokens"),
       A("t0.categories", "freq", "most frequent category")]),
    Q("G-068", "discourse", "en", "C1",
      "In the Hyland (2005) analysis, what is the raw frequency of the hedges category, and what is its per-million rate?",
      [T("discourse_analysis", corpus="C1")],
      [N("t0.categories.[interactional.hedges].freq", "hedges freq"),
       N("t0.categories.[interactional.hedges].per_million", "hedges per million")]),
    Q("G-069", "discourse", "en", "C1",
      "In the Hyland (2005) analysis, what is the raw frequency of the boosters category?",
      [T("discourse_analysis", corpus="C1")],
      [N("t0.categories.[interactional.boosters].freq", "boosters freq")]),

    # ------------------------------------------------------------------ #
    # POS / grammar audit (3)
    # ------------------------------------------------------------------ #
    Q("G-070", "pos_grammar", "en", "C1",
      "What is the total token count of the POS analysis, and which POS tag is the most frequent?",
      [T("get_pos_analysis", corpus="C1")],
      [N("t0.total_tokens", "total tokens"),
       S("t0.distribution_top[0].pos", "most frequent POS")]),
    Q("G-071", "pos_grammar", "en", "C1",
      "How many NOUN tokens does the POS analysis report?",
      [T("get_pos_analysis", corpus="C1")],
      [N("t0.distribution_top[pos=NOUN].freq", "NOUN count")]),
    Q("G-072", "pos_grammar", "en", "C1",
      "According to the grammar audit, how many passive-voice constructions are there in the corpus?",
      [T("grammar_query", corpus="C1", patterns=["passive_voice"])],
      [N("t0.counts.passive_voice", "passive count")]),

    # ------------------------------------------------------------------ #
    # traps (8)
    # ------------------------------------------------------------------ #
    Q("G-073", "trap", "en", "C1",
      "How many hits does the word 'zebra' have in this corpus?",
      [T("search_concordance", corpus="C1", query="zebra", window=3, limit=10)],
      [TZ("t0.total_matches", "total hits")], trap=True),
    Q("G-074", "trap", "ar", "C4",
      "كم نتيجة لكلمة «زرافة» في هذا المحتوى؟",
      [T("search_concordance", corpus="C4", query="زرافة", window=3, limit=10)],
      [TZ("t0.total_matches", "total hits")], trap=True),
    Q("G-075", "trap", "en", "C2",
      "What is the log ratio of the word 'zebra' in the keyness table vs the press corpus?",
      [T("compute_keyness", corpus="C2", reference="C3", limit=100)],
      [X("t0.positive_keywords[term=zebra]", "row for 'zebra'")]),
    Q("G-076", "trap", "en", "C1",
      "Run the CQL query '[[[not-a-query' and report the number of hits.",
      [T("search_cql", corpus="C1", query="[[[not-a-query", window=3)],
      [TE]),
    Q("G-077", "trap", "en", "C1",
      "What is the Flesch reading-ease score of this corpus?",
      [],
      [TN]),
    Q("G-078", "trap", "en", "C1",
      "How many unique trilateral roots does the English corpus have according to the Arabic morphology engine?",
      [],
      [TN]),
    Q("G-079", "trap", "en", "C1",
      "How many 8-grams occur at least twice in this corpus?",
      [T("get_ngrams", corpus="C1", n=8, min_freq=2, min_range=1, limit=50)],
      [C("t0.top_ngrams", "8-gram rows")], trap=True),
    Q("G-080", "trap", "en", "C1",
      "How many collocates does 'zebra' have within a window of 5?",
      [T("compute_collocations", corpus="C1", node="zebra", window=5, min_freq=1)],
      [C("t0.top_collocates", "collocate rows")], trap=True),
]


def validate_bank() -> list[str]:
    """Structural validation: unique ids, at least one gold entry per
    question, tools present unless trap_no_tool, corpus symbols known."""
    problems: list[str] = []
    seen: set[str] = set()
    known = {"C1", "C2", "C3", "C4", "C5", "C6"}
    for q in QUESTION_BANK:
        if q["id"] in seen:
            problems.append(f"duplicate id {q['id']}")
        seen.add(q["id"])
        if not q["gold_spec"]:
            problems.append(f"{q['id']}: empty gold spec")
        kinds = {g["kind"] for g in q["gold_spec"]}
        if kinds == {"trap_no_tool"} and q["tools"]:
            problems.append(f"{q['id']}: trap_no_tool must not declare tools")
        if kinds != {"trap_no_tool"} and not q["tools"]:
            problems.append(f"{q['id']}: non-trap question without tools")
        if q["corpus"] not in known:
            problems.append(f"{q['id']}: unknown corpus symbol {q['corpus']}")
        for t in q["tools"]:
            if t["name"] == "get_corpus_overview" or "corpus" in t["args"]:
                if "corpus" in t["args"] and t["args"]["corpus"] not in known:
                    problems.append(f"{q['id']}: unknown corpus in tool args")
    if len(QUESTION_BANK) != 80:
        problems.append(f"bank has {len(QUESTION_BANK)} questions, expected 80")
    return problems
