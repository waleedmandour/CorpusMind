"""r10 — Arabic register detection recognizes fully-vocalized Classical text.

Functional sweep finding (v1.2.14-9, post-r9): `detect_arabic_register`
matched its Classical/dialectal marker sets against RAW whitespace tokens,
so (a) any diacritized token could never match its bare marker — and
Classical religious text, the tool's primary target, is exactly the text
that ships fully vocalized (a hadith sample scored 1.0 MSA) — and (b) the
"يا أيها" marker is a bigram and could never match a single-word set, so it
was dead weight. Matching now runs on tashkeel-stripped tokens on both
sides, and the bigram is tested as a phrase over the stripped stream.

Pure Python — no CAMeL data needed; runs in CI.
"""

from nlp.arabic.pipeline import detect_arabic_register

# Fully-vocalized hadith fragment (harakat + shadda on nearly every word).
VOCALIZED_CLASSICAL = (
    "قَالَ رَسُولُ اللَّهِ صَلَّى اللهُ عَلَيْهِ وَسَلَّمَ إنَّ الصَّلاةَ نور"
)
# Same text, bare spelling — both must score identically.
BARE_CLASSICAL = "قال رسول الله صلى الله عليه وسلم إن الصلاة نور"

PLAIN_MSA = "الطلاب يدرسون في الجامعة كل صباح"
VOCALIZED_MSA = "الطُّلَّاب يَدْرُسُونَ فِي الجَامِعَةِ كُلَّ صَبَاحٍ"
DIALECTAL = "كيفك شو عم تعمل هلق"


def _winner(dist: dict[str, float]) -> str:
    return max(dist, key=lambda k: dist[k])


def test_vocalized_classical_text_is_classical() -> None:
    """The regression: vocalized Classical used to score 1.0 MSA."""
    dist = detect_arabic_register(VOCALIZED_CLASSICAL)
    assert _winner(dist) == "classical"
    assert dist["classical"] >= 0.5


def test_bare_and_vocalized_spellings_agree() -> None:
    """Tashkeel stripping must make both spellings of the same text agree."""
    assert detect_arabic_register(VOCALIZED_CLASSICAL) == detect_arabic_register(
        BARE_CLASSICAL
    )


def test_plain_msa_is_unclassified_as_before() -> None:
    """Marker-less MSA keeps the pre-fix distribution (msa=1.0)."""
    assert detect_arabic_register(PLAIN_MSA) == {
        "classical": 0.0,
        "msa": 1.0,
        "dialectal": 0.0,
    }


def test_vocalized_msa_does_not_become_classical() -> None:
    """Diacritics alone must not fabricate Classical matches."""
    dist = detect_arabic_register(VOCALIZED_MSA)
    assert _winner(dist) == "msa"


def test_dialectal_markers_still_match() -> None:
    """Multiple dialect markers outweigh the always-present +1 MSA mass.

    (One marker yields a structural 0.5/0.5 tie with msa by the +1-smoothing
    formula, so this sample carries three.)
    """
    dist = detect_arabic_register("ليش هيك شو عملت فيه")
    assert _winner(dist) == "dialectal"
    assert dist["dialectal"] == 0.75


def test_bigram_marker_ya_ayyuha_counts() -> None:
    """'يا أيها' is a bigram; as a set member it could never match."""
    dist = detect_arabic_register("يا أيها الناس اتقوا ربكم")
    assert dist["classical"] > 0.0
