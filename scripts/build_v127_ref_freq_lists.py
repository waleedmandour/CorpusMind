#!/usr/bin/env python3
"""v1.2.7 (§5) — build three REAL, open-licensed reference frequency lists.

1. ar/arz-wiki-dialectal-top1000.tsv   — Egyptian Arabic Wikipedia sample
   (arz.wikipedia.org; the wiki is written in Egyptian Masri dialect).
   License: CC BY-SA 4.0. Sampled via the MediaWiki API (random article
   generator, plain-text extracts), ~2,000 articles.
2. en/pd-persuasive-top1000.tsv        — public-domain persuasive essays &
   oratory via Project Gutenberg: The Federalist Papers (#1404), Common
   Sense (#147), A Vindication of the Rights of Woman (#3420).
   License: public domain.
3. en/ellipse-learner-top1000.tsv      — ELLIPSE corpus (Crossley et al.
   2023), ~5,000 English-learner essays, official GitHub CSV.
   License: CC BY-NC-SA 4.0.

Output format matches the existing reference-data lists:
  # comment lines start with '#'
  word<TAB>frequency<TAB>per_million
"""
import csv
import hashlib
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

OUT_DIR = str(Path(__file__).resolve().parents[1] / "reference-data" / "reference-corpora")
UA = {"User-Agent": "CorpusMind-reference-builder/1.2.7 (corpus linguistics tool; contact: repo maintainer)"}


def fetch(url: str, timeout: int = 60, retries: int = 5) -> bytes:
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = min(30, 3 * (attempt + 1))
                try:
                    wait = max(wait, int(e.headers.get("Retry-After", "0") or 0))
                except Exception:
                    pass
                print(f"  429 rate-limited, waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(f"retries exhausted: {url}")


def write_tsv(path: str, header_lines: list[str], counts: Counter, total: int, top_n: int = 1000) -> str:
    top = counts.most_common(top_n)
    lines = list(header_lines)
    for rank, (word, freq) in enumerate(top, 1):
        pm = freq / total * 1_000_000
        lines.append(f"{word}\t{freq}\t{pm:.1f}")
    content = "\n".join(lines) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    print(f"wrote {path}: {len(top)} types, {total} tokens, sha256={digest}")
    return digest


def tokenize_english(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z']*", text.lower())


def tokenize_arabic(text: str) -> list[str]:
    # strip Arabic diacritics + tatweel, keep only Arabic letter runs
    text = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", text)
    return re.findall(r"[\u0621-\u064A]+", text)


# ------------------------------------------------------------------ #
# 1. Dialectal Arabic tweets (multi-dialect, MIT)
# ------------------------------------------------------------------ #

DIALECT_TWEETS_URL = (
    "https://huggingface.co/datasets/amgadhasan/arabic_tweets_dialects/"
    "resolve/main/data/train-00000-of-00001.parquet"
)


def build_dialect_tweets() -> None:
    """Dialectal Arabic frequency list from ~148k dialect-labelled tweets
    (Hugging Face: amgadhasan/arabic_tweets_dialects, MIT)."""
    import pandas as pd

    raw = fetch(DIALECT_TWEETS_URL, timeout=240)
    df = pd.read_parquet(io.BytesIO(raw))
    print(f"  dialect tweets: {len(df)} rows, dialects: {df['dialect'].nunique()}")

    counts: Counter = Counter()
    total = 0
    for text in df["text"].tolist():
        if not isinstance(text, str) or not text.strip():
            continue
        # strip mentions, URLs, hashtag marker, non-Arabic noise; tweets are
        # genuinely colloquial — exactly the register an MSA reference lacks
        text = re.sub(r"[@#]\S+", " ", text)
        text = re.sub(r"https?://\S+", " ", text)
        toks = [t for t in tokenize_arabic(text) if len(t) > 1]
        counts.update(toks)
        total += len(toks)
    print(f"  tokens: {total}")
    header = [
        "# Dialectal Arabic tweets frequency list (top 1000 words)",
        "# Source: Hugging Face dataset amgadhasan/arabic_tweets_dialects —",
        "# ~148,000 dialect-labelled Arabic tweets (Gulf, Levantine, Egyptian,",
        "# Libyan, ...). A genuine colloquial/dialectal register reference,",
        "# unlike MSA news corpora. Mentions/URLs/hashtags stripped;",
        "# diacritics and tatweel removed; Arabic-letter runs only.",
        "# License: MIT (dataset card). Format: word<TAB>frequency<TAB>per_million",
    ]
    write_tsv(f"{OUT_DIR}/ar/dialectal-arabic-tweets-top1000.tsv", header, counts, total)


# ------------------------------------------------------------------ #
# 2. Public-domain persuasive essays & oratory (Gutenberg)
# ------------------------------------------------------------------ #

GUTENBERG_TEXTS = [
    ("https://www.gutenberg.org/cache/epub/1404/pg1404.txt", "The Federalist Papers (Hamilton, Madison, Jay, 1788)"),
    ("https://www.gutenberg.org/cache/epub/147/pg147.txt", "Common Sense (Thomas Paine, 1776)"),
    ("https://www.gutenberg.org/cache/epub/3420/pg3420.txt", "A Vindication of the Rights of Woman (Mary Wollstonecraft, 1792)"),
]


def build_persuasive() -> None:
    counts: Counter = Counter()
    total = 0
    for url, label in GUTENBERG_TEXTS:
        try:
            raw = fetch(url, timeout=90).decode("utf-8", errors="replace")
        except Exception as e:
            print(f"  gutenberg error {url}: {e}", file=sys.stderr)
            continue
        # strip Gutenberg boilerplate between the *** markers
        m = re.search(r"\*\*\* ?START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", raw, re.S)
        if m:
            raw = raw[m.end():]
        m = re.search(r"\*\*\* ?END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK", raw)
        if m:
            raw = raw[: m.start()]
        toks = tokenize_english(raw)
        counts.update(toks)
        total += len(toks)
        print(f"  {label}: +{len(toks)} tokens")
    header = [
        "# Persuasive essays & oratory frequency list (top 1000 words)",
        "# Built from public-domain persuasive texts via Project Gutenberg:",
        "#   - The Federalist Papers (Hamilton, Madison & Jay, 1788) [ebook #1404]",
        "#   - Common Sense (Thomas Paine, 1776) [ebook #147]",
        "#   - A Vindication of the Rights of Woman (Mary Wollstonecraft, 1792) [ebook #3420]",
        "# A persuasive-GENRE comparable corpus: argumentation, exhortation, polemic.",
        "# Gutenberg boilerplate stripped; English letter runs lowercased.",
        "# License: public domain. Format: word<TAB>frequency<TAB>per_million",
    ]
    write_tsv(f"{OUT_DIR}/en/pd-persuasive-top1000.tsv", header, counts, total)


# ------------------------------------------------------------------ #
# 3. ELLIPSE learner English corpus
# ------------------------------------------------------------------ #

ELLIPSE_URL = (
    "https://raw.githubusercontent.com/scrosseye/ELLIPSE-Corpus/main/"
    "ELLIPSE_Final_github_train.csv"
)


def build_ellipse() -> None:
    raw = fetch(ELLIPSE_URL, timeout=120).decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    counts: Counter = Counter()
    total = 0
    essays = 0
    col = None
    for row in reader:
        if col is None:
            # the essay text lives in the `full_text` column (verified schema)
            col = next((k for k in row if k and k.strip().lower() == "full_text"), None)
            if col is None:
                col = next((k for k in row if k and "full" in k.lower() and "text" in k.lower()), None)
            if col is None:
                raise SystemExit(f"no full_text column in ELLIPSE CSV: {list(row)[:10]}")
        text = (row.get(col) or "").strip()
        if not text:
            continue
        essays += 1
        toks = tokenize_english(text)
        counts.update(toks)
        total += len(toks)
    print(f"  ELLIPSE: {essays} essays, {total} tokens")
    header = [
        "# Learner English frequency list (top 1000 words)",
        "# Source: ELLIPSE — English Language Learner Insight, Proficiency and",
        "# Skills Evaluation Corpus (Crossley et al. 2023), training split,",
        "# ~5,000 argumentative essays written by English-language learners",
        "# in US secondary standardized testing (grades 8-12). An ICLE-style",
        "# open learner-English reference (the closed ICLE itself is not",
        "# redistributable).",
        "# License: CC BY-NC-SA 4.0. Format: word<TAB>frequency<TAB>per_million",
    ]
    write_tsv(f"{OUT_DIR}/en/ellipse-learner-top1000.tsv", header, counts, total)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "arz", "dialect"):
        build_dialect_tweets()
    if which in ("all", "persuasive"):
        build_persuasive()
    if which in ("all", "ellipse"):
        build_ellipse()
