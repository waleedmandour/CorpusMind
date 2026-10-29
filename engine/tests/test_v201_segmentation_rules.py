"""v2.0.1 — principled Arabic segmentation rules (Tier 1 of the AraSEG
error-budget plan).

Three engine-semantics changes to ``nlp.arabic.pipeline.split_arabic_sentences``,
each with a measured error class on the AraSEG PA dev set (FP 2,894 / FN 4,926
after the PR #28 evaluator fix):

1. terminal-run collapse (` . . . `, `!!!`, `؟!` → ONE boundary) — targets the
   2,336 '.' false positives;
2. `؛` demoted from terminal to clause-level — targets 259 FPs at the cost of
   ≤ 90 FNs (gold ends a sentence at only 90/349 `؛`);
3. quote-parity guard — targets 297 FPs where ؟/! inside unclosed quotes ended
   a sentence mid-quotation.

These are engine-semantics changes: they shift ``sentence_idx`` for every
Arabic consumer (KWIC context, collocation windows, CQL ``within sentence``,
per-sentence sentiment, CAF, Gale–Church). Documented in CHANGELOG 2.0.1.
"""

from nlp.arabic.pipeline import split_arabic_sentences


# ------------------------------------------------------------------ rule 1 --
def test_ellipsis_dot_run_is_one_boundary() -> None:
    # spaced ellipsis: 3 old boundaries collapse into 1
    parts = split_arabic_sentences("قال كلاما . . . ثم سكت.")
    assert len(parts) == 2
    assert parts[0].endswith(". . .")
    assert parts[1] == "ثم سكت."


def test_masked_word_ellipsis_single_boundary() -> None:
    # masked word (الم . . . . اء): 4 old boundaries → 1
    parts = split_arabic_sentences("قال الم . . . . اء ثم تابع كلامه.")
    assert len(parts) == 2


def test_exclamation_run_is_one_boundary() -> None:
    parts = split_arabic_sentences("يا إلهي!!! هل تصدق؟")
    assert len(parts) == 2
    assert parts[0].endswith("!!!")


def test_mixed_run_question_exclamation_is_one_boundary() -> None:
    parts = split_arabic_sentences("ما هذا؟! غريب حقا.")
    assert len(parts) == 2


def test_unicode_ellipsis_then_text_is_one_boundary() -> None:
    # U+2026 already a terminal; must not double-split when followed by another
    parts = split_arabic_sentences("كلام مؤجل… ثم اكمل.")
    assert len(parts) == 2


# ------------------------------------------------------------------ rule 2 --
def test_semicolon_no_longer_ends_sentence() -> None:
    # v2.0.1 behavior change: ؛ is clause-level (26% of gold breaks only)
    parts = split_arabic_sentences("جاء سعيد؛ ثم ذهب.")
    assert len(parts) == 1


def test_semicolon_line_still_breaks_on_newline() -> None:
    parts = split_arabic_sentences("جاء سعيد؛\nثم ذهب.")
    assert len(parts) == 2


# ------------------------------------------------------------------ rule 3 --
def test_quote_guard_closes_at_closing_quote() -> None:
    parts = split_arabic_sentences("قال: «ماذا تريد؟» ثم ذهب.")
    assert len(parts) == 2
    assert parts[0].endswith("»")
    assert parts[1] == "ثم ذهب."


def test_quote_guard_only_fires_with_terminal_inside() -> None:
    # closing quote WITHOUT a terminal inside must NOT split
    parts = split_arabic_sentences("قرأت «الكتاب المفيد» بالكامل.")
    assert len(parts) == 1


def test_unmatched_quote_bounded_by_newline() -> None:
    # one stray quote cannot suppress boundaries beyond its own line
    parts = split_arabic_sentences("قال: «ماذا تريد؟\nثم ذهب.")
    assert len(parts) == 2


def test_two_quoted_sentences_split_at_each_closing_quote() -> None:
    parts = split_arabic_sentences("«مرحبا؟» «أهلا؟»")
    assert len(parts) == 2


# ------------------------------------------------------- preserved behavior --
def test_plain_terminals_unchanged() -> None:
    parts = split_arabic_sentences("اللغة العربية جميلة. هل هذا صحيح؟ نعم، بالتأكيد!")
    assert len(parts) == 3
    assert parts[0].endswith(".")
    assert parts[1].endswith("؟")


def test_decimal_protection_preserved() -> None:
    parts = split_arabic_sentences("ارتفع المؤشر 3.4 في المئة. ثم انخفض.")
    assert len(parts) == 2
    assert "3.4" in parts[0]


def test_newlines_always_break() -> None:
    parts = split_arabic_sentences("سطر أول\nسطر ثان\n")
    assert len(parts) == 2


def test_no_terminal_whole_text_one_segment() -> None:
    parts = split_arabic_sentences("نص بدون ترقيم نهائي")
    assert len(parts) == 1


def test_empty_and_whitespace_inputs() -> None:
    assert split_arabic_sentences("") == []
    assert split_arabic_sentences("   ") == []


def test_quranic_ornate_brackets_do_not_split_without_terminal() -> None:
    parts = split_arabic_sentences("قال تعالى: ﴿إنما المؤمنون إخوة﴾ في سورة الحجرات.")
    assert len(parts) == 1
