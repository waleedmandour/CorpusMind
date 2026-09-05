"""Build compact USAS top-level lexicons for CorpusMind's semantic tagset.

Source: UCREL Multilingual-USAS lexicons
  https://github.com/UCREL/Multilingual-USAS
  License: CC BY-NC-SA 4.0 (attribution + non-commercial + share-alike)

The full lexicons (English ~1.2 MB, Arabic ~1.26 MB) map each lemma to
fine-grained semantic tags. CorpusMind's semantic tagset works at the
TOP LEVEL of the USAS hierarchy (the letter category: A, B, ... Z), so
this script produces compact TSVs:

    lemma<TAB>top<TAB>first_tag

where ``top`` is the first tag's top-level letter and ``first_tag`` the
first full tag (kept for future fine-grained support). Arabic lemmas are
stored diacritics-stripped to match CAMeL lemmas at query time.

Usage:
    python scripts/build_usas_lexicons.py [--output-dir reference-data/tagsets]

Files are written next to a README.md documenting provenance and license.
"""
from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

SOURCES = {
    "en": "https://raw.githubusercontent.com/UCREL/Multilingual-USAS/master/English/semantic_lexicon_en.tsv",
    "ar": "https://raw.githubusercontent.com/UCREL/Multilingual-USAS/master/Arabic/semantic_lexicon_arabic.tsv",
}

ARABIC_DIACRITICS = "\u064B\u064C\u064D\u064E\u064F\u0650\u0651\u0652\u0670\u0640"


def strip_diacritics(text: str) -> str:
    """Remove Arabic harakat/tatweel so lexicon lookups match CAMeL lemmas."""
    return "".join(c for c in text if c not in ARABIC_DIACRITICS)


def top_level(tag: str) -> str:
    """'A1.1.1' -> 'A', 'Z5' -> 'Z', 'B1' -> 'B'. Handles +/-/@/% modifiers."""
    letters = "".join(c for c in tag if c.isalpha())
    return letters[:1].upper() if letters else "O"


def process(raw: str, lang: str) -> str:
    lines = []
    header_seen = False
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.rstrip("\n").split("\t")
        if not header_seen:
            header_seen = True  # header row: lemma, pos?, semantic_tags
            continue
        lemma = parts[0].strip()
        # English: lemma \t POS \t semantic_tags ; Arabic: lemma \t semantic_tags
        tags_field = parts[-1] if len(parts) >= 2 else ""
        tags = tags_field.split()
        if not lemma or not tags:
            continue
        first = tags[0].rstrip("-+@%")
        top = top_level(first)
        key = strip_diacritics(lemma) if lang == "ar" else lemma.lower()
        lines.append(f"{key}\t{top}\t{first}")
    # dedupe by lemma keeping the first occurrence (most common reading)
    seen: set[str] = set()
    out: list[str] = ["lemma\ttop\tfirst_tag"]
    for line in lines:
        lemma = line.split("\t", 1)[0]
        if lemma in seen:
            continue
        seen.add(lemma)
        out.append(line)
    return "\n".join(out) + "\n"


def main() -> None:
    import urllib.request

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output-dir", type=Path, default=Path("reference-data/tagsets"))
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for lang, url in SOURCES.items():
        dest = args.output_dir / f"usas-{lang}-top.tsv"
        print(f"Downloading {url} …")
        with urllib.request.urlopen(url, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
        text = process(raw, lang)
        dest.write_text(text, encoding="utf-8")
        n = text.count("\n") - 1
        print(f"  wrote {n} entries → {dest}")


if __name__ == "__main__":
    sys.exit(main())
