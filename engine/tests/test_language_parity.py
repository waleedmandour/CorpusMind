"""SQL scalar ↔ Python mirror parity tests (v1.2.11).

The SQL normalizers (arnorm / fanorm / urnorm / hinorm) registered in
storage.session must stay in lockstep with their Python mirrors in
nlp/normalizers.py (+ stats.service.ar_norm for Arabic): the same corpus
fixture must produce the same aggregation key whether it is folded in SQL
(GROUP BY on the scalar) or in Python (streaming paths, stopword sets).

Fixtures cover the documented failure points: Persian/Urdu yeh/kaf
lookalikes, Urdu gol-he variants, ZWNJ modes, Devanagari nukta +
chandrabindu, digits (all scripts pass through), and the Arabic regression
guarantee that arnorm itself is unchanged.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import func, select

os.environ["CORPUSMIND_DB_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["CORPUSMIND_DATA_DIR"] = "/tmp/cm-test-data"

from nlp.normalizers import fa_norm, hi_norm, ur_norm
from storage.session import dispose_db, init_db


@pytest.fixture
async def session():
    from storage.session import get_session

    await init_db()
    async for s in get_session():
        yield s
    await dispose_db()


# --------------------------------------------------------------------------- #
# Fixtures — (raw, expected) pairs exercising the documented rules
# --------------------------------------------------------------------------- #

FA_FIXTURES = [
    # Arabic kaf/yeh lookalikes fold onto the Persian forms
    ("كتاب", "کتاب"),
    ("كتاب‌ها", "کتاب‌ها"),
    # Persian kaf/yeh are untouched
    ("کتاب", "کتاب"),
    ("می‌روم", "می‌روم"),  # ZWNJ keep-mode default
    # Arabic-specific rules must NOT fire: teh marbuta and alef variants
    # stay exactly as written (task rule: no Arabic rules on fa). Note علي
    # legitimately folds its Arabic yeh to Persian yeh — that is the
    # keyboard-lookalike unification, not an Arabic alef rule.
    ("مدرسة", "مدرسة"),
    ("علي", "علی"),
    ("أحمد", "أحمد"),
    # digits pass through in every script
    ("۱۲۳", "۱۲۳"),
    ("0456", "0456"),
]

UR_FIXTURES = [
    # bare Arabic he folds onto gol he; do-chashmi he stays distinct
    ("یہ", "یہ"),
    ("کہانی", "کہانی"),
    # bari ye vs yeh are NOT folded together
    ("لڑکی", "لڑکی"),
    ("بھی", "بھی"),
    ("۱۲۳", "۱۲۳"),
]

HI_FIXTURES = [
    # precomposed nukta and decomposed forms agree after NFC + nukta removal
    ("क़ानून", "कानून"),
    ("क़", "क"),
    # chandrabindu folds onto anusvara
    ("हैँ", "हैं"),
    # danda and double danda are preserved (never punctuation-folded)
    ("राम।", "राम।"),
    ("॥श्री॥", "॥श्री॥"),
    # Devanagari digits pass through
    ("१२३", "१२३"),
]


class TestSqlPythonParity:
    async def test_fa_parity(self, session) -> None:
        for raw, _expected in FA_FIXTURES:
            sql_val = (
                await session.execute(select(func.fanorm(raw)))
            ).scalar()
            assert sql_val == fa_norm(raw), f"fa parity failed for {raw!r}"

    async def test_fa_zwnj_modes_parity(self, session) -> None:
        raw = "می‌روم"
        for mode in ("keep", "space", "strip"):
            sql_val = (
                await session.execute(select(func.fanorm(raw, mode)))
            ).scalar()
            assert sql_val == fa_norm(raw, mode), f"zwnj mode {mode} diverged"

    async def test_ur_parity(self, session) -> None:
        for raw, _expected in UR_FIXTURES:
            sql_val = (
                await session.execute(select(func.urnorm(raw)))
            ).scalar()
            assert sql_val == ur_norm(raw), f"ur parity failed for {raw!r}"

    async def test_ur_zwnj_modes_parity(self, session) -> None:
        raw = "کیا\u200cہے"
        for mode in ("keep", "space", "strip"):
            sql_val = (
                await session.execute(select(func.urnorm(raw, mode)))
            ).scalar()
            assert sql_val == ur_norm(raw, mode), f"zwnj mode {mode} diverged"

    async def test_hi_parity(self, session) -> None:
        for raw, _expected in HI_FIXTURES:
            sql_val = (
                await session.execute(select(func.hinorm(raw)))
            ).scalar()
            assert sql_val == hi_norm(raw), f"hi parity failed for {raw!r}"

    async def test_sql_group_by_collapses_variants(self, session) -> None:
        """The aggregation motivation: ك/ک and ي/ی variants must count as
        ONE row under the SQL scalar — the exact trap that breaks Persian
        corpora typed on an Arabic keyboard."""
        vals = ["كتاب", "کتاب"]  # same word, two keyboard traditions
        keys = {
            (await session.execute(select(func.fanorm(v)))).scalar() for v in vals
        }
        assert len(keys) == 1

    async def test_sql_never_applies_arabic_rules_to_fa(self, session) -> None:
        """Teh marbuta / alef variants must survive fanorm — the pre-v1.2.11
        behavior (arnorm applied to any language) destroyed them."""
        sql_val = (
            await session.execute(select(func.fanorm("مدرسة أحمد")))
        ).scalar()
        assert "ة" in sql_val and "أ" in sql_val


class TestDocumentedRules:
    """The expected-value columns of the fixtures, asserted directly
    (these are the documented normalization rules, test-pinned)."""

    def test_fa_expected_values(self) -> None:
        for raw, expected in FA_FIXTURES:
            assert fa_norm(raw) == expected, f"fa {raw!r}"

    def test_ur_expected_values(self) -> None:
        for raw, expected in UR_FIXTURES:
            assert ur_norm(raw) == expected, f"ur {raw!r}"

    def test_hi_expected_values(self) -> None:
        for raw, expected in HI_FIXTURES:
            assert hi_norm(raw) == expected, f"hi {raw!r}"

    def test_zwnj_modes_documented(self) -> None:
        zwnj = "\u200c"
        word = f"می{zwnj}روم"
        assert fa_norm(word, "keep") == word
        assert fa_norm(word, "space") == "می روم"
        assert fa_norm(word, "strip") == "میروم"
        with pytest.raises(ValueError):
            fa_norm(word, "nonsense")

    def test_arabic_norm_unchanged_golden(self) -> None:
        """Arabic regression guard: arnorm output is pinned byte-for-byte."""
        from stats.service import ar_norm

        assert ar_norm("أَلْكِتَابُ") == "الكتاب"
        assert ar_norm("مدرسة علي") == "مدرسه علي"  # ة→ه, ى→ي (alef maksura)
        assert ar_norm("ٱلرَّحْمَن") == "ٱلرحمن"  # alef wasla is NOT folded (pinned as-is)
