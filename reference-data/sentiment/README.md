# Sentiment lexicons (v1.2.8, review #8)

This directory documents the layered sentiment data model. It ships EMPTY
of third-party emotion data on purpose.

## What is bundled (inside the app, no setup)

- The Appraisal cue lexicon and the starter valence lexicons (English +
  Arabic) are curated in the engine source
  (`engine/sentiment/lexicons.py`), not in this directory. They are
  CorpusMind's own data and always available.

## What is user-configured (optional upgrade)

The full NRC Emotion Lexicon (Mohammad & Turney 2013; 8 emotion
categories + polarity flags, English and Arabic) is supported as a
user-supplied resource. NRC's Terms of Use (clause 5) forbid
redistribution of the data, so CorpusMind cannot include it here. To
enable full 8-emotion coverage:

1. Download the official lexicon:
   https://saifmohammad.com/WebPages/emolex.html
   (direct zip: https://saifmohammad.com/WebDocs/Lexicons/NRC-Emotion-Lexicon.zip)
2. Convert it once on your machine:

       python scripts/build_sentiment_lexicons.py <path-to-zip> --out <dir>

   This writes `nrc-emolex-en.tsv` and `nrc-emolex-ar.tsv` in CorpusMind's
   compact format (lemma, emotions, polarity).
3. Point the engine at the directory by setting
   `CORPUSMIND_SENTIMENT_LEXICON_DIR=<dir>` (or the Settings surface) and
   restarting. Keep the files local: the NRC terms of use do not permit
   sharing them onward.

Without the upgrade the Sentiment view runs on the bundled starter lexicon
and reports coverage as "starter" honestly; nothing silently degrades.

## Citation

- Martin, J. R., & White, P. R. R. (2005). The Language of Evaluation:
  Appraisal in English. Palgrave Macmillan.
- Mohammad, S., & Turney, P. (2013). Crowdsourcing a Word-Emotion
  Association Lexicon. Computational Intelligence, 29(3), 436-465.
