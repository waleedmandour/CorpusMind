"""Declarative catalogue of all bundled reference corpora.

Each entry describes one reference corpus that CorpusMind can download and
install on the user's machine. The catalogue is intentionally declarative —
the ``manager`` reads it at runtime and decides what to download based on
what the user requests.

Adding a new bundled reference:
  1. Append a ``ReferenceCorpusSpec`` to ``BUNDLED_REFERENCES``.
  2. Make sure the source URL supports HTTP Range requests (for resumable
     downloads). Most static-file HTTPS hosts do; S3 and GitHub Releases do.
  3. Compute the SHA-256 of the file you expect the user to receive and put
     it in ``sha256``. The manager will refuse to "install" a download whose
     hash does not match.
  4. Pick a ``format``:
       - ``tsv_freq``  — tab-separated ``word<TAB>freq`` (one row per type)
       - ``csv_freq``  — comma-separated, same shape
       - ``json_freq`` — ``[{"word": ..., "freq": ...}, ...]``
     The ``keyness_bridge`` knows how to load all three.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ReferenceFormat = Literal["tsv_freq", "csv_freq", "json_freq"]
ReferenceLanguage = Literal["en", "ar"]


@dataclass(frozen=True, slots=True)
class ReferenceCorpusSpec:
    """One downloadable reference corpus.

    The ``sha256`` field is the contract: if the bytes the user receives do
    not hash to this value, the download is rejected. This is what makes the
    system trustworthy — a MITM or a silently-corrupted mirror cannot inject
    a bogus reference corpus.
    """

    name: str
    """Short, stable identifier used in URLs and the manifest. Lowercase,
    ASCII, no spaces. Example: ``be06-top1000``."""

    display_name: str
    """Human-readable label shown in the UI. Example: ``BE06 — British
    English Written (top 1000)``."""

    language: ReferenceLanguage
    """BCP-47 short tag. Used to auto-select the reference when the target
    corpus is in the same language."""

    description: str
    """One-paragraph academic description, including the source corpus,
    approximate size, and what it's good for (keyness, register comparison,
    etc.)."""

    source_url: str
    """HTTPS URL the manager downloads from. Must support Range requests."""

    sha256: str
    """Lowercase hex SHA-256 of the canonical file. 64 chars."""

    format: ReferenceFormat
    """How the file is structured on disk. The ``keyness_bridge`` parses
    each format differently."""

    size_hint: str
    """Human-readable approximate size for UI display (e.g. ``~5 KB``)."""

    license: str
    """SPDX identifier or short license name. Surfaced in the UI so the
    user can cite it in their Methods section."""

    citation: str
    """APA/author-date citation string. Surfaced in the UI for the same
    reason as ``license``."""

    genre: str = "mixed"
    """Register/genre tag (academic, news, spoken, fiction, blog, legal,
    medical, mixed). Used for register-aware keyness warnings."""

    min_corpus_tokens: int = 1_000
    """Soft minimum target-corpus size below which this reference is not
    recommended. The UI shows a warning, not a hard block."""

    tags: tuple[str, ...] = field(default_factory=tuple)
    """Free-form tags for filtering (e.g. ``("written", "british")``)."""


# --------------------------------------------------------------------------- #
# Catalogue
# --------------------------------------------------------------------------- #
# The catalogue is intentionally short — each entry must have a real,
# verified SHA-256. Bundling a fictional URL+hash would create a worse UX
# than not listing the reference at all (download would always fail).
#
# The BE06 top-1000 list is shipped in-repo under reference-data/, so its
# source_url points at the GitHub raw URL and the SHA-256 is computed from
# the committed file. The other entries are placeholders for follow-up
# PRs that should add real open-access references (BNC Baby sample,
# arTenTen subset, etc.) — they are marked ``available=False`` in the API
# response so the UI can grey them out.

BUNDLED_REFERENCES: list[ReferenceCorpusSpec] = [
    ReferenceCorpusSpec(
        name="be06-top1000",
        display_name="BE06 — British English Written (top 1000)",
        language="en",
        description=(
            "Top-1000 word-frequency list derived from BE06, a 1-million-token "
            "British English written reference corpus matching the Brown family "
            "design. Suitable for keyness comparison against small-to-medium "
            "English target corpora. Distributed as a tab-separated "
            "word/frequency list (~5 KB)."
        ),
        source_url=(
            "https://raw.githubusercontent.com/waleedmandour/CorpusMind/main/"
            "reference-data/reference-corpora/en/be06-freq-top1000.tsv"
        ),
        # SHA-256 of the committed file at path
        # reference-data/reference-corpora/en/be06-freq-top1000.tsv.
        # Computed once and pinned; any tampering or truncation will fail
        # verification and the manager will refuse to install the file.
        # Update this value if and only if the source file is intentionally
        # refreshed — and bump the catalogue ``version`` at the same time.
        sha256="3e632ede66b44db04a59f88ba43f0ce17aca1dca6de72242e8907a284cb4da89",
        format="tsv_freq",
        size_hint="~5 KB",
        license="CC-BY-4.0",
        citation=(
            "Baker, P. (2009). BE06: A 1-million-word corpus of British English "
            "(version 1). Lancaster University."
        ),
        genre="written",
        min_corpus_tokens=1_000,
        tags=("english", "british", "written"),
    ),
    ReferenceCorpusSpec(
        name="bnc-baby-sample",
        display_name="BNC Baby — British National Corpus sample (4M words)",
        language="en",
        description=(
            "A 4-million-token balanced sample of the British National Corpus "
            "covering four registers: academic, news, fiction, and spoken. The "
            "gold-standard reference for British English keyness analysis."
        ),
        source_url="",  # populated when the file is hosted on a stable mirror
        sha256="",
        format="tsv_freq",
        size_hint="~12 MB",
        license="BNC Licence (research-only)",
        citation=(
            "The British National Corpus, version 3 (BNC XML Edition). 2007. "
            "Distributed by Oxford University Computing Services on behalf of "
            "the BNC Consortium."
        ),
        genre="mixed",
        min_corpus_tokens=10_000,
        tags=("english", "british", "balanced"),
    ),
    # v0.1.17: New freely-licensed reference corpora
    ReferenceCorpusSpec(
        name="leipzig-english-news",
        display_name="Leipzig English News — top 100",
        language="en",
        description=(
            "Top-100 word-frequency list from the Leipzig Corpora Collection "
            "(English news). Suitable as a general English reference for "
            "keyness comparison. Based on the Leipzig Wortschatz project."
        ),
        source_url=(
            "https://raw.githubusercontent.com/waleedmandour/CorpusMind/main/"
            "reference-data/reference-corpora/en/leipzig-english-news-top100.tsv"
        ),
        sha256="607f814be77d159fa4a86bfd3cbd1d3fc12c395903d56dd8e116109257ccc70e",
        format="tsv_freq",
        size_hint="~2 KB",
        license="CC-BY-4.0",
        citation=(
            "Goldhahn, D., Eckart, T., & Quasthoff, U. (2012). Building Large "
            "Monolingual Corpora at the Leipzig Corpora Collection. LREC 2012."
        ),
        genre="news",
        min_corpus_tokens=500,
        tags=("english", "news", "leipzig"),
    ),
    ReferenceCorpusSpec(
        name="quranic-arabic",
        display_name="Quranic Arabic — word frequency",
        language="ar",
        description=(
            "Word-frequency list derived from the Quranic Arabic Corpus "
            "(corpus.quran.com). Suitable as a Classical/Quranic Arabic "
            "reference for keyness analysis of Quranic or classical Arabic "
            "target corpora. 85 most frequent word types."
        ),
        source_url=(
            "https://raw.githubusercontent.com/waleedmandour/CorpusMind/main/"
            "reference-data/reference-corpora/ar/quranic-arabic-freq.tsv"
        ),
        sha256="08419d575732e4181af3c0ab524f1912729bbf00cd5385f4c9ad6086d07a8129",
        format="tsv_freq",
        size_hint="~2 KB",
        license="GPL-3.0",
        citation=(
            "Dukes, K., Atwell, E., & Sharaf, A. (2010). The Quranic Arabic "
            "Dependency Treebank. LREC 2010."
        ),
        genre="classical",
        min_corpus_tokens=100,
        tags=("arabic", "quranic", "classical"),
    ),
    ReferenceCorpusSpec(
        name="camel-arabic",
        display_name="CAMeL Arabic Frequency List — top 1000",
        language="ar",
        description=(
            "Top-1000 Arabic word-frequency list from CAMeL Lab, derived "
            "from CAMeLBERT pretraining data (OSCAR + Wikipedia + Gumar + "
            "OSIAN). Suitable as a Modern Standard Arabic reference for "
            "keyness analysis."
        ),
        source_url=(
            "https://raw.githubusercontent.com/waleedmandour/CorpusMind/main/"
            "reference-data/reference-corpora/ar/camel-arabic-top1000.tsv"
        ),
        sha256="d5558cd419c8d46bdc958064cb97f963d1ea793866414c025906ec15033512ed",
        format="tsv_freq",
        size_hint="~15 KB",
        license="CC-BY-SA-4.0",
        citation=(
            "Inoue, G., Alhafni, B., Baimukan, N., Bouamor, H., Habash, N., "
            "& Bouzoubaa, K. (2021). CAMeL Tools: An Open Source Python "
            "Toolkit for Arabic NLP. arXiv."
        ),
        genre="mixed",
        min_corpus_tokens=500,
        tags=("arabic", "msa", "camel"),
    ),
    # arTenTen and enTenTen are NOT included — they require a Sketch Engine
    # subscription and cannot be redistributed. The entries below are kept
    # as placeholders so users know they exist but need a Sketch Engine
    # account to access.
    ReferenceCorpusSpec(
        name="ar-tenten-sample",
        display_name="arTenTen — Arabic Web Corpus (requires Sketch Engine)",
        language="ar",
        description=(
            "Frequency list sampled from arTenTen12, a multi-billion-token "
            "Arabic web corpus. NOT downloadable — requires a Sketch Engine "
            "subscription. Suitable as a Modern Standard Arabic reference "
            "for keyness analysis of Arabic target corpora."
        ),
        source_url="",
        sha256="",
        format="tsv_freq",
        size_hint="~8 MB",
        license="CC-BY-NC-4.0 (Sketch Engine)",
        citation=(
            "Arts, T., Belikov, A., Kilgarriff, A., et al. (2014). arTenTen: "
            "Arabic Corpus. In: Proceedings of WAC7."
        ),
        genre="web",
        min_corpus_tokens=5_000,
        tags=("arabic", "web", "msa"),
    ),
]
