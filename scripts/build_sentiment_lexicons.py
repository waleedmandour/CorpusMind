"""Convert the official NRC Emotion Lexicon into CorpusMind's sentiment TSVs.

NRC's Terms of Use (clause 5) FORBID redistribution of the lexicon data, so
CorpusMind cannot ship it. Instead, this script runs ON THE USER'S MACHINE
against a copy they downloaded themselves from the official page:

    https://saifmohammad.com/WebPages/emolex.html
    (direct zip: https://saifmohammad.com/WebDocs/Lexicons/NRC-Emotion-Lexicon.zip)

It writes two TSVs in CorpusMind's compact format:

    nrc-emolex-en.tsv   lemma <TAB> emotions(comma-separated) <TAB> polarity
    nrc-emolex-ar.tsv   same, from the Arabic column of the official file

Point the engine at the output directory with
CORPUSMIND_SENTIMENT_LEXICON_DIR (or Settings > Sentiment lexicon dir) and
restart; the Sentiment view's emotion layer upgrades from the bundled
starter lexicon to full 8-emotion coverage and the UI reports it.

Usage:
    python scripts/build_sentiment_lexicons.py \
        /path/to/NRC-Emotion-Lexicon.zip --out ~/.corpusmind/resources/sentiment
    # a directory containing the official zip's contents works too

The script reads the lexicon, it never re-distributes it: the output files
are derived data for the user's own local research use, consistent with the
NRC research-use terms.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import zipfile
from pathlib import Path

EMOTIONS = (
    "anger",
    "anticipation",
    "disgust",
    "fear",
    "joy",
    "sadness",
    "surprise",
    "trust",
)
POLARITY_FLAGS = ("negative", "positive")

HEADER = "lemma\temotions\tpolarity\n"


_INNER = "NRC-Emotion-Lexicon/OneFilePerLanguage/Arabic-NRC-EmoLex.txt"


def _read_rows(fh):
    """Parse the official per-language file (header-mapped columns)."""
    text = io.TextIOWrapper(fh, encoding="utf-8")
    reader = csv.reader(text, delimiter="\t")
    header = [h.strip() for h in next(reader)]
    idx = {name: i for i, name in enumerate(header)}
    needed = ["English Word", "Arabic Word", *EMOTIONS, *POLARITY_FLAGS]
    missing = [n for n in needed if n not in idx]
    if missing:
        raise SystemExit(f"Unexpected EmoLex header (missing {missing}): {header}")
    for row in reader:
        if len(row) < len(header):
            continue
        flags = {name: row[idx[name]].strip() for name in needed[2:]}
        yield row[idx["English Word"]].strip(), flags, row[idx["Arabic Word"]].strip()


def _iter_rows(src: Path):
    """Yield (english_word, flags, arabic_word) rows; zip or directory."""
    if src.suffix.lower() == ".zip":
        with zipfile.ZipFile(src) as zf, zf.open(_INNER) as fh:
            yield from _read_rows(fh)
    else:
        with (src / _INNER).open("rb") as fh:
            yield from _read_rows(fh)


def _to_entry(flags: dict) -> tuple[str, int]:
    emotions = [e for e in EMOTIONS if flags.get(e) == "1"]
    pos = flags.get("positive") == "1"
    neg = flags.get("negative") == "1"
    if pos and not neg:
        polarity = 1
    elif neg and not pos:
        polarity = -1
    else:
        # EmoLex words can be associated with both flags (rare) or neither;
        # keep the emotion tags but make the word valence-neutral.
        polarity = 0
    return ",".join(emotions), polarity


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "source",
        type=Path,
        help="Official NRC-Emotion-Lexicon.zip (or an extracted directory)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=Path.home() / ".corpusmind" / "resources" / "sentiment",
        help="Output directory (default: ~/.corpusmind/resources/sentiment)",
    )
    args = ap.parse_args()

    if not args.source.exists():
        print(f"ERROR: source not found: {args.source}", file=sys.stderr)
        return 2

    en_rows: list[tuple[str, str, str]] = []
    ar_rows: list[tuple[str, str, str]] = []
    seen_en: set[str] = set()

    for en_word, flags, ar_word in _iter_rows(args.source):
        emotions, polarity = _to_entry(flags)
        if en_word.lower() not in seen_en:
            seen_en.add(en_word.lower())
            en_rows.append((en_word.lower(), emotions, str(polarity)))
        if ar_word and (emotions or polarity != 0):
            # Keep the Arabic-script term; skip empty translations and pure
            # transliterations are not an issue here (the official file uses
            # Arabic script for the Arabic column).
            ar_rows.append((ar_word, emotions, str(polarity)))

    args.out.mkdir(parents=True, exist_ok=True)
    en_path = args.out / "nrc-emolex-en.tsv"
    ar_path = args.out / "nrc-emolex-ar.tsv"
    with en_path.open("w", encoding="utf-8") as fh:
        fh.write(HEADER)
        fh.writelines(f"{a}\t{b}\t{c}\n" for a, b, c in en_rows)
    with ar_path.open("w", encoding="utf-8") as fh:
        fh.write(HEADER)
        fh.writelines(f"{a}\t{b}\t{c}\n" for a, b, c in ar_rows)

    print(f"English: {len(en_rows):>6} lemmas -> {en_path}")
    print(f"Arabic:  {len(ar_rows):>6} terms  -> {ar_path}")
    print(
        "\nNext: set CORPUSMIND_SENTIMENT_LEXICON_DIR to\n"
        f"  {args.out}\n"
        "and restart the engine. The Sentiment view will report full "
        "coverage.\nRemember: NRC data may not be redistributed - keep the "
        "converted files local to your machine."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
