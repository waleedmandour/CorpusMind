"""post-v2.0.1 — quote-guard tightening regression tests.

Regression: a stray self-paired quote (the apostrophe in ``Qur'an``, an inch
mark ``27"``) opened the parity guard with no closer anywhere on the line, so
every terminal after it was suppressed to end-of-line ("قرأ الطالب Qur'an
كاملا. ثم ذهب. وعاد." came out as 1 sentence instead of 3).

Fix semantics (engine/nlp/arabic/pipeline.py):
  (a) a quote style opens the guard only if its closer exists LATER ON THE
      SAME LINE — otherwise the char is literal;
  (b) ASCII ' removed from _QUOTE_PAIRS entirely (apostrophes never guard).

The work-order checklist maps to tests: Qur'an / sha'b / 27" / balanced «؟» /
spaced ellipsis / ؛ clause / unclosed quote + newline. The balanced-quote,
ellipsis and ؛ behaviours also stay guarded by test_v201_segmentation_rules.py
from the v2.0.1 cycle — they must not regress.
"""

from nlp.arabic.pipeline import _QUOTE_PAIRS, split_arabic_sentences


# ------------------------------------------------------- (b) ' never guards --
def test_ascii_apostrophe_removed_from_quote_pairs() -> None:
    assert "'" not in _QUOTE_PAIRS


def test_quran_apostrophe_does_not_disable_boundaries() -> None:
    # the reported regression: 1 sentence before the fix, 3 after
    parts = split_arabic_sentences("قرأ الطالب Qur'an كاملا. ثم ذهب. وعاد.")
    assert len(parts) == 3
    assert parts[0].endswith("كاملا.")
    assert parts[1] == "ثم ذهب."
    assert parts[2] == "وعاد."


def test_shab_apostrophe_does_not_disable_boundaries() -> None:
    parts = split_arabic_sentences("الشعب sha'b أصيل. ثم رحل.")
    assert len(parts) == 2
    assert parts[0].endswith("أصيل.")
    assert parts[1] == "ثم رحل."


def test_two_apostrophes_on_one_line_still_do_not_guard() -> None:
    # even when a closer char exists later on the line, ASCII ' is not a
    # quote style at all (b), so it can never open the guard
    parts = split_arabic_sentences("قال sha'b ثم 'saw' راح. عاد بعد.")
    assert len(parts) == 2


# ------------------------------------------- (a) same-line closer condition --
def test_stray_double_quote_is_literal() -> None:
    # inch-mark 27": the only " on the line — no closer later on the line
    parts = split_arabic_sentences('بلغ الطول 27" بالضبط. ثم توقف.')
    assert len(parts) == 2
    assert parts[0].endswith('بالضبط.')
    assert parts[1] == "ثم توقف."


def test_unclosed_guillemet_is_literal_on_its_line() -> None:
    # « with no » on the same line: the ؟ inside must end the sentence
    parts = split_arabic_sentences("قال: «ماذا تريد؟ ثم صمت.")
    assert len(parts) == 2
    assert parts[0].endswith("تريد؟")


def test_unclosed_quote_newline_still_bounds_suppression() -> None:
    # work-order case: unclosed quote + newline — the guard never opens (no
    # closer on the line) AND a newline would reset it anyway
    parts = split_arabic_sentences("قال: «ماذا تريد؟\nثم ذهب.")
    assert len(parts) == 2


# ------------------------------------------------ behaviour kept from v2.0.1 --
def test_balanced_guillemets_with_terminal_inside() -> None:
    # work-order case "balanced «؟»": the terminal inside a genuinely closed
    # quotation still moves the boundary to the closing quote (v2.0.1 rule 3)
    parts = split_arabic_sentences("قال: «ماذا تريد؟» ثم ذهب.")
    assert len(parts) == 2
    assert parts[0].endswith("»")
    assert parts[1] == "ثم ذهب."


def test_self_paired_double_quote_as_real_pair_still_guards() -> None:
    # " with its closer on the same line is a REAL quotation: the terminal
    # inside is suppressed and the boundary lands on the closing quote
    parts = split_arabic_sentences('قال "مرحبا. وذهب" ثم عاد.')
    assert len(parts) == 2
    assert parts[0].endswith('"')
    assert parts[1] == "ثم عاد."


def test_spaced_ellipsis_still_one_boundary() -> None:
    # work-order case "spaced ellipsis" (v2.0.1 rule 1)
    parts = split_arabic_sentences("قال كلاما . . . ثم سكت.")
    assert len(parts) == 2
    assert parts[0].endswith(". . .")


def test_arabic_semicolon_still_clause_level() -> None:
    # work-order case "؛ clause" (v2.0.1 rule 2)
    parts = split_arabic_sentences("جاء سعيد؛ ثم ذهب.")
    assert len(parts) == 1
