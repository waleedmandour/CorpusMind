"""Script/language detection tests (v1.2.11) — mixed and near-miss inputs.

nlp/script_detect.py exists to prevent one specific wrong behavior:
Arabic-script text being routed into Arabic resources when the text is
actually Persian or Urdu. These tests pin the ordered rules from the module
docstring, including the tricky near-misses.
"""
from __future__ import annotations

from nlp.script_detect import detect_language


class TestCoreDetection:
    def test_plain_arabic(self) -> None:
        assert detect_language("الكتاب على الطاولة") == "ar"

    def test_plain_urdu(self) -> None:
        assert detect_language("میں ٹہل کر اسکول گیا") == "ur"

    def test_plain_persian(self) -> None:
        assert detect_language("من کتاب‌ها را می‌خوانم") == "fa"

    def test_plain_hindi(self) -> None:
        assert detect_language("राम जंगल में गया और फल खाया") == "hi"

    def test_english(self) -> None:
        assert detect_language("The quick brown fox jumps over the lazy dog.") == "en"

    def test_empty(self) -> None:
        assert detect_language("") == "en"


class TestNearMisses:
    """The cases the old binary 'any Arabic-script char -> ar' got wrong."""

    def test_urdu_with_persian_loanwords(self) -> None:
        # چ پ ژ گ occur in Urdu too — the Urdu-specific letters must win.
        assert detect_language("چائے پینا اچھا ہے") == "ur"

    def test_persian_without_zwnj(self) -> None:
        # Persian typed without any ZWNJ still has پ چ ژ گ.
        assert detect_language("پدر و مادر خوب هستند") == "fa"

    def test_persian_zwnj_only_signal(self) -> None:
        # No distinctive letters, but ZWNJ present: never Arabic.
        assert detect_language("می\u200cروم") == "fa"

    def test_arabic_with_persian_quote_letters(self) -> None:
        # Arabic text quoting a Persian word containing گ — the Arabic-only
        # letters ة/ؤ must not be overridden by a single loanword unless
        # Urdu letters are present. The ordered rules run Urdu first, then
        # Persian letters (which this text HAS, via the quote), so this is
        # honestly ambiguous — the contract is only that it is NOT silent
        # Arabic-rules territory for rule-less languages. Documented:
        # Persian letters present => fa.
        assert detect_language("قال الشاعر الفارسي: گل") == "fa"

    def test_urdu_specific_letters_beat_everything(self) -> None:
        assert detect_language("ڈاکٹر نے ٹوکا کہ ڑ کیس") == "ur"

    def test_mixed_english_farsi(self) -> None:
        assert detect_language("He said: کتاب خوب است") == "fa"

    def test_mixed_hindi_english(self) -> None:
        assert detect_language("This is राम की किताब") == "hi"

    def test_hindi_beats_arabic_script_scan(self) -> None:
        # Devanagari is checked FIRST so Urdu/Arabic char classes never
        # swallow a Hindi sentence.
        assert detect_language("यह एक वाक्य है।") == "hi"

    def test_bare_msa_no_distinctive_letters_still_ar(self) -> None:
        # Plain MSA often has no distinctive letters; the fallback keeps it
        # "ar" (the only Arabic-script language WITH rule support), and the
        # limitation is documented in the module docstring.
        assert detect_language("قال هو") == "ar"
