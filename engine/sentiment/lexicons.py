"""Lexicons for the layered sentiment analysis (v1.2.8, review #8).

Three data sources, each with a different licensing story:

1. APPRAISAL_CUES + STARTER_VALENCE_EN / STARTER_VALENCE_AR — curated in
   this repository for CorpusMind. Fully bundled, no external license.

2. NRC EmoLex (Mohammad & Turney 2013) — the full 8-emotion taxonomy
   (Plutchik's primaries + polarity flags) for English AND Arabic. Its
   Terms of Use CLAUSE 5 FORBIDS REDISTRIBUTION ("Do not redistribute the
   data. Direct interested parties to the lexicon home page."), so the
   data is NOT shipped. The user downloads it from the official page
   (https://saifmohammad.com/WebPages/emolex.html), converts it once with
   scripts/build_sentiment_lexicons.py, and points the engine at the
   directory via CORPUSMIND_SENTIMENT_LEXICON_DIR (or the Settings
   surface). When configured, the emotion layer upgrades from the small
   starter coverage to the full lexicon; when not, everything still works
   with honest coverage reporting — never silent zeros.

3. Boosters (graduation.force cues) double as intensity multipliers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

EMOTIONS: tuple[str, ...] = (
    "anger",
    "anticipation",
    "disgust",
    "fear",
    "joy",
    "sadness",
    "surprise",
    "trust",
)

SENTIMENT_FRAMEWORK_CITATION = (
    "Framework: Appraisal Theory (Martin, J. R., & White, P. R. R. (2005). "
    "The Language of Evaluation: Appraisal in English. Palgrave Macmillan) "
    "- Attitude (Affect, Judgment, Appreciation), Engagement, Graduation. "
    "Valence/emotion layer: curated starter lexicon, optionally upgraded "
    "with the NRC Emotion Lexicon (Mohammad, S., & Turney, P. (2013). "
    "Crowdsourcing a Word-Emotion Association Lexicon. Computational "
    "Intelligence 29(3)), which is downloaded by the user and never "
    "redistributed (NRC Terms of Use, clause 5)."
)

SENTIMENT_METHOD = "appraisal-nuanced-v1"

# --------------------------------------------------------------------------- #
# Layer A - Appraisal cue lexicon (bundled, English)
# --------------------------------------------------------------------------- #
# Categories follow Martin & White (2005). The engagement/graduation/affect
# cue sets mirror the discourse lens' martinwhite2005 categories so the two
# surfaces stay comparable; Judgment and Appreciation are added here because
# the Sentiment view needs the full Attitude triad. Honest starter subsets:
# every set is deliberately incomplete and documented as such in the UI.

APPRAISAL_CUES: dict[str, frozenset[str]] = {
    "engagement.entertain": frozenset({
        "perhaps", "possibly", "probably", "may", "might", "could",
        "seem", "appear", "likely", "presumably", "apparently",
        "it seems", "arguably",
    }),
    "engagement.attribute": frozenset({
        "according to", "cited in", "reported", "claimed", "as x argues",
        "as x claims", "as x states", "x suggests", "x found that",
    }),
    "engagement.deny": frozenset({
        "not", "no", "never", "none", "nor", "without",
    }),
    "engagement.counter": frozenset({
        "but", "although", "while", "despite", "however", "yet",
        "nevertheless", "ironically", "even so", "still",
    }),
    "engagement.proclaim": frozenset({
        "clearly", "obviously", "of course", "undoubtedly", "certainly",
        "indeed", "necessarily", "naturally", "not surprisingly",
        "as is well known",
    }),
    "graduation.force": frozenset({
        "very", "extremely", "highly", "deeply", "strongly", "utterly",
        "completely", "entirely", "totally", "so", "such", "too",
        "remarkably", "strikingly", "considerably", "substantially",
    }),
    "graduation.focus": frozenset({
        "slightly", "somewhat", "kind of", "sort of", "borderline",
        "genuinely", "truly", "virtually", "almost", "quite",
    }),
    "attitude.affect": frozenset({
        "surprisingly", "unfortunately", "fortunately", "happily",
        "sadly", "regrettably", "interestingly", "importantly", "notably",
        "worryingly", "encouragingly",
    }),
    "attitude.judgment": frozenset({
        # Evaluations of human behaviour (social esteem / social sanction).
        "honest", "dishonest", "corrupt", "brave", "cowardly", "generous",
        "selfish", "ethical", "unethical", "expert", "incompetent",
        "capable", "reliable", "unreliable", "fair", "unfair", "heroic",
        "cruel", "responsible", "reckless", "professionally", "skillful",
        "careless", "trustworthy", "deceitful", "patient", "rude",
        "polite", "hardworking", "lazy",
    }),
    "attitude.appreciation": frozenset({
        # Evaluations of things, texts, and states of affairs.
        "beautiful", "ugly", "elegant", "harmonious", "balanced",
        "captivating", "dull", "remarkable", "innovative", "simplistic",
        "refined", "crude", "impressive", "mediocre", "stunning",
        "fascinating", "boring", "exquisite", "outstanding", "flawed",
        "robust", "fragile", "valuable", "worthless", "compelling",
    }),
}

# Categories that participate in the Attitude triad (reported separately).
ATTITUDE_CATEGORIES = ("attitude.affect", "attitude.judgment", "attitude.appreciation")
ENGAGEMENT_CATEGORIES = tuple(
    k for k in APPRAISAL_CUES if k.startswith("engagement.")
)
GRADUATION_CATEGORIES = tuple(
    k for k in APPRAISAL_CUES if k.startswith("graduation.")
)

BOOSTERS: frozenset[str] = APPRAISAL_CUES["graduation.force"]
NEGATION_WORDS: frozenset[str] = frozenset({"not", "no", "never", "none", "nor"})


# --------------------------------------------------------------------------- #
# Layer B - bundled starter valence lexicons (ours; lemma-level)
# --------------------------------------------------------------------------- #
# lemma -> (valence: +1 | -1, emotions). The emotion tags are restricted to
# EMOTIONS and are only attached where the association is unambiguous, so
# the starter set gives PARTIAL emotion coverage; the UI says so and offers
# the NRC EmoLex upgrade. English keys are lowercase lemmas.

STARTER_VALENCE_EN: dict[str, tuple[int, tuple[str, ...]]] = {
    # --- positive / joy ---
    "good": (1, ()), "great": (1, ("joy",)), "excellent": (1, ("joy",)),
    "wonderful": (1, ("joy",)), "amazing": (1, ("surprise", "joy")),
    "fantastic": (1, ("joy",)), "happy": (1, ("joy",)), "happiness": (1, ("joy",)),
    "glad": (1, ("joy",)), "delighted": (1, ("joy",)), "pleased": (1, ("joy",)),
    "enjoy": (1, ("joy",)), "enjoyed": (1, ("joy",)), "love": (1, ("joy",)),
    "loved": (1, ("joy",)), "like": (1, ()), "beautiful": (1, ("joy",)),
    "brilliant": (1, ("joy",)), "superb": (1, ("joy",)),
    "outstanding": (1, ("joy",)), "perfect": (1, ("joy",)),
    "success": (1, ("joy", "trust")), "successful": (1, ("joy", "trust")),
    "win": (1, ("joy",)), "won": (1, ("joy",)), "achieve": (1, ("trust",)),
    "achievement": (1, ("trust", "joy")), "benefit": (1, ()),
    "improve": (1, ("anticipation",)), "improved": (1, ("anticipation",)),
    "progress": (1, ("anticipation",)), "advance": (1, ("anticipation",)),
    "hope": (1, ("anticipation",)), "hopeful": (1, ("anticipation",)),
    "promising": (1, ("anticipation",)), "confident": (1, ("trust",)),
    "confidence": (1, ("trust",)), "trust": (1, ("trust",)),
    "support": (1, ("trust",)), "help": (1, ("trust",)),
    "helpful": (1, ("trust",)), "effective": (1, ("trust",)),
    "efficient": (1, ("trust",)), "strong": (1, ("trust",)),
    "powerful": (1, ("trust",)), "valuable": (1, ()),
    "important": (1, ()), "significant": (1, ()),
    "positive": (1, ("joy",)), "right": (1, ("trust",)),
    "best": (1, ("joy",)), "better": (1, ()),
    # --- negative / sadness ---
    "bad": (-1, ()), "poor": (-1, ()), "terrible": (-1, ("fear", "sadness")),
    "awful": (-1, ("sadness",)), "horrible": (-1, ("disgust",)),
    "sad": (-1, ("sadness",)), "sadness": (-1, ("sadness",)),
    "unhappy": (-1, ("sadness",)), "unfortunately": (-1, ("sadness",)),
    "regret": (-1, ("sadness",)), "disappointing": (-1, ("sadness",)),
    "disappointed": (-1, ("sadness",)), "disappointment": (-1, ("sadness",)),
    "fail": (-1, ("sadness", "fear")), "failed": (-1, ("sadness", "fear")),
    "failure": (-1, ("sadness", "fear")), "lose": (-1, ("sadness",)),
    "lost": (-1, ("sadness",)), "loss": (-1, ("sadness",)),
    "problem": (-1, ("fear",)), "problems": (-1, ("fear",)),
    "difficult": (-1, ("fear",)), "difficulty": (-1, ("fear",)),
    "hard": (-1, ()), "weak": (-1, ("fear",)), "weakness": (-1, ("fear",)),
    "negative": (-1, ()), "wrong": (-1, ("anger",)),
    "harm": (-1, ("anger",)), "harmful": (-1, ("anger",)),
    "damage": (-1, ("anger",)), "danger": (-1, ("fear",)),
    "dangerous": (-1, ("fear",)), "risk": (-1, ("fear",)),
    "risky": (-1, ("fear",)), "threat": (-1, ("fear",)),
    "crisis": (-1, ("fear",)), "worry": (-1, ("fear",)),
    "worried": (-1, ("fear",)), "worrying": (-1, ("fear",)),
    "concern": (-1, ("fear",)), "concerned": (-1, ("fear",)),
    "fear": (-1, ("fear",)), "afraid": (-1, ("fear",)),
    "anxious": (-1, ("fear",)), "anxiety": (-1, ("fear",)),
    # --- negative / anger ---
    "angry": (-1, ("anger",)), "anger": (-1, ("anger",)),
    "furious": (-1, ("anger",)), "outrage": (-1, ("anger",)),
    "outrageous": (-1, ("anger",)), "hate": (-1, ("anger",)),
    "hated": (-1, ("anger",)), "hostile": (-1, ("anger",)),
    "injustice": (-1, ("anger",)), "unfair": (-1, ("anger",)),
    "corrupt": (-1, ("anger", "disgust")), "selfish": (-1, ("anger",)),
    "cruel": (-1, ("anger", "disgust")), "violent": (-1, ("anger", "fear")),
    "violence": (-1, ("anger", "fear")), "attack": (-1, ("anger", "fear")),
    "blame": (-1, ("anger",)), "conflict": (-1, ("anger", "fear")),
    # --- negative / disgust ---
    "disgust": (-1, ("disgust",)), "disgusting": (-1, ("disgust",)),
    "gross": (-1, ("disgust",)), "shameful": (-1, ("disgust",)),
    "dishonest": (-1, ("disgust",)), "ugly": (-1, ("disgust",)),
    "worthless": (-1, ("sadness", "disgust")),
    # --- surprise (both polarities possible; tagged neutral-positive here) ---
    "surprise": (1, ("surprise",)), "surprising": (1, ("surprise",)),
    "surprisingly": (1, ("surprise",)), "unexpected": (1, ("surprise",)),
    "sudden": (1, ("surprise",)), "suddenly": (1, ("surprise",)),
    "shock": (-1, ("surprise", "fear")), "shocking": (-1, ("surprise", "fear")),
    "remarkable": (1, ("surprise", "joy")),
    # competence / character (Judgment-flavoured valence)
    "talented": (1, ("trust",)), "skilled": (1, ("trust",)),
    "competent": (1, ("trust",)), "reliable": (1, ("trust",)),
    "incompetent": (-1, ("disgust",)), "unreliable": (-1, ("disgust",)),
}

# Arabic starter set: unambiguous, high-frequency emotion/valence words in
# their citation (singular masculine) form. Lookup strips diacritics and
# matches both the stored lemma and the surface form.
STARTER_VALENCE_AR: dict[str, tuple[int, tuple[str, ...]]] = {
    "سعيد": (1, ("joy",)), "سعيدة": (1, ("joy",)), "سعادة": (1, ("joy",)),
    "فرح": (1, ("joy",)), "فرحان": (1, ("joy",)), "مبسوط": (1, ("joy",)),
    "رائع": (1, ("joy",)), "رائعة": (1, ("joy",)), "جميل": (1, ("joy",)),
    "جميلة": (1, ("joy",)), "ممتاز": (1, ("joy",)), "ممتازة": (1, ("joy",)),
    "حب": (1, ("joy",)), "محبة": (1, ("joy",)), "يحب": (1, ("joy",)),
    "أحب": (1, ("joy",)), "استمتع": (1, ("joy",)), "ممتع": (1, ("joy",)),
    "نجاح": (1, ("joy", "trust")), "نجح": (1, ("joy", "trust")),
    "فوز": (1, ("joy",)), "فاز": (1, ("joy",)), "إنجاز": (1, ("trust", "joy")),
    "أمل": (1, ("anticipation",)), "متفائل": (1, ("anticipation",)),
    "تفاؤل": (1, ("anticipation",)), "ثقة": (1, ("trust",)),
    "موثوق": (1, ("trust",)), "دعم": (1, ("trust",)), "يساعد": (1, ("trust",)),
    "مساعدة": (1, ("trust",)), "مفيد": (1, ("trust",)),
    "قوي": (1, ("trust",)), "قوية": (1, ("trust",)), "جيد": (1, ()),
    "جيدة": (1, ()), "إيجابي": (1, ("joy",)),
    "مفاجأة": (1, ("surprise",)), "مفاجئ": (1, ("surprise",)),
    "مذهل": (1, ("surprise", "joy")), "مدهش": (1, ("surprise", "joy")),
    "حزين": (-1, ("sadness",)), "حزن": (-1, ("sadness",)),
    "حزينة": (-1, ("sadness",)), "أسف": (-1, ("sadness",)),
    "يأس": (-1, ("sadness",)), "محبط": (-1, ("sadness",)),
    "خيبة": (-1, ("sadness",)), "فشل": (-1, ("sadness", "fear")),
    "فقد": (-1, ("sadness",)), "خسر": (-1, ("sadness",)),
    "خسارة": (-1, ("sadness",)), "سيء": (-1, ()), "سيئة": (-1, ()),
    "ضعيف": (-1, ("fear",)), "ضعيفة": (-1, ("fear",)),
    "مشكلة": (-1, ("fear",)), "مشاكل": (-1, ("fear",)),
    "صعب": (-1, ("fear",)), "صعوبة": (-1, ("fear",)),
    "خطر": (-1, ("fear",)), "خطير": (-1, ("fear",)), "مخاطرة": (-1, ("fear",)),
    "تهديد": (-1, ("fear",)), "أزمة": (-1, ("fear",)),
    "قلق": (-1, ("fear",)), "قلقان": (-1, ("fear",)),
    "خوف": (-1, ("fear",)), "خائف": (-1, ("fear",)), "أخاف": (-1, ("fear",)),
    "غاضب": (-1, ("anger",)), "غضب": (-1, ("anger",)),
    "غاضبة": (-1, ("anger",)), "كره": (-1, ("anger",)),
    "يكره": (-1, ("anger",)), "عدوان": (-1, ("anger", "fear")),
    "عنف": (-1, ("anger", "fear")), "عنيف": (-1, ("anger", "fear")),
    "ظلم": (-1, ("anger",)), "مظلوم": (-1, ("anger",)),
    "هجوم": (-1, ("anger", "fear")), "صراع": (-1, ("anger", "fear")),
    "قبيح": (-1, ("disgust",)), "مقزز": (-1, ("disgust",)),
    "فاضح": (-1, ("disgust",)), "كاذب": (-1, ("disgust",)),
    "فاسد": (-1, ("anger", "disgust")), "أناني": (-1, ("anger",)),
    "مؤسف": (-1, ("sadness",)), "سوء": (-1, ()), "سلبي": (-1, ()),
}

STARTER_COVERAGE_NOTE = (
    "Starter valence lexicon: a curated, deliberately small subset. "
    "Configure the NRC Emotion Lexicon (CORPUSMIND_SENTIMENT_LEXICON_DIR) "
    "for full 8-emotion coverage; the engine never redistributes NRC data."
)


# --------------------------------------------------------------------------- #
# Layer B upgrade - user-configured NRC EmoLex (never redistributed)
# --------------------------------------------------------------------------- #

EMOLEX_FILENAME = "nrc-emolex-{lang}.tsv"
# Our converted TSV columns: lemma \t emotions(comma-separated) \t polarity


@dataclass(frozen=True, slots=True)
class ValenceEntry:
    polarity: int  # +1 | -1 | 0
    emotions: tuple[str, ...]


def _lexicon_dirs() -> list[str]:
    """Candidate directories for user-supplied emotion lexicons."""
    dirs: list[str] = []
    from app.settings import get_settings

    configured = (get_settings().sentiment_lexicon_dir or "").strip()
    if configured:
        dirs.append(configured)
    # Sensible default inside the app data dir: drop the converted files at
    # <data_dir>/resources/sentiment/ and they are picked up on restart.
    try:
        data_dir = str(get_settings().data_dir)
    except Exception:
        data_dir = ""
    if data_dir:
        dirs.append(os.path.join(data_dir, "resources", "sentiment"))
    return dirs


@lru_cache(maxsize=2)
def load_emolex(language: str) -> dict[str, ValenceEntry] | None:
    """Load the user-configured NRC EmoLex (converted TSV) for a language.

    Returns None when not configured/absent — the caller then falls back to
    the bundled starter lexicon and reports the upgrade path. Cached per
    process; empty lexicon files also yield None (nothing to upgrade with).
    """
    lang = (language or "en").lower()
    lex: dict[str, ValenceEntry] = {}
    for d in _lexicon_dirs():
        path = os.path.join(d, EMOLEX_FILENAME.format(lang=lang))
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                next(fh)  # header
                for line in fh:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) < 3 or not parts[0]:
                        continue
                    emotions = tuple(
                        e for e in parts[1].split(",") if e in EMOTIONS
                    )
                    try:
                        polarity = int(parts[2])
                    except ValueError:
                        polarity = 0
                    lex.setdefault(
                        parts[0].lower(), ValenceEntry(polarity, emotions)
                    )
        except OSError:
            continue
    return lex or None


def emolex_status(language: str) -> dict:
    """Honest availability report for the emotion layer of ``language``."""
    lang = (language or "en").lower()
    configured = load_emolex(lang)
    dirs = _lexicon_dirs()
    return {
        "available": configured is not None,
        "source": (
            "NRC Emotion Lexicon (user-configured; Mohammad & Turney 2013)"
            if configured is not None
            else "bundled starter lexicon (curated subset)"
        ),
        "coverage": "full" if configured is not None else "starter",
        "expected_path": (
            os.path.join(dirs[0], EMOLEX_FILENAME.format(lang=lang))
            if dirs
            else EMOLEX_FILENAME.format(lang=lang)
        ),
        "upgrade_hint": (
            "Download the NRC Emotion Lexicon from "
            "https://saifmohammad.com/WebPages/emolex.html, convert it with "
            "scripts/build_sentiment_lexicons.py, and set "
            "CORPUSMIND_SENTIMENT_LEXICON_DIR (NRC Terms of Use forbid "
            "redistribution, so the app cannot ship the data itself)."
            if configured is None
            else ""
        ),
    }
