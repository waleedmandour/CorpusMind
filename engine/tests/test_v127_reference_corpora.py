"""v1.2.7 (§5) — three register-specialised reference corpora.

Each new catalogue entry ships a committed frequency list and pins its
SHA-256. These tests re-hash the COMMITTED files so a stale, corrupted or
hand-edited list fails CI — the same trust contract as the download-time
hash verification in the manager.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from reference_corpus.registry import BUNDLED_REFERENCES

REPO_ROOT = Path(__file__).resolve().parents[2]
REF_DATA = REPO_ROOT / "reference-data" / "reference-corpora"


def _spec(name: str):
    spec = next((s for s in BUNDLED_REFERENCES if s.name == name), None)
    assert spec is not None, f"{name} missing from BUNDLED_REFERENCES"
    return spec


def _committed_path(spec) -> Path:
    # source_url points at the committed file on GitHub raw; derive the
    # local path from the URL's tail.
    return REF_DATA / spec.source_url.split("/reference-corpora/", 1)[1]


def _load_rows(spec) -> list[tuple[str, int]]:
    path = _committed_path(spec)
    assert path.is_file(), f"committed frequency list missing: {path}"
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        assert len(parts) >= 2, f"malformed row in {path}: {line!r}"
        rows.append((parts[0], int(parts[1])))
    return rows


def test_three_new_reference_specs_registered():
    names = {s.name for s in BUNDLED_REFERENCES}
    assert {"dialectal-arabic-tweets", "pd-persuasive", "ellipse-learner"} <= names


def test_new_specs_sha256_matches_committed_files():
    """The pinned sha256 must equal the hash of the committed TSV."""
    for name in ("dialectal-arabic-tweets", "pd-persuasive", "ellipse-learner"):
        spec = _spec(name)
        path = _committed_path(spec)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert spec.sha256 == digest, (
            f"{name}: registry sha256 does not match committed file - "
            "refresh the list (scripts/build_v127_ref_freq_lists.py) and "
            "re-pin the hash."
        )


def test_frequency_lists_are_wellformed():
    for name in ("dialectal-arabic-tweets", "pd-persuasive", "ellipse-learner"):
        spec = _spec(name)
        rows = _load_rows(spec)
        assert len(rows) >= 500, f"{name}: expected ~1000 types, got {len(rows)}"
        freqs = [f for _, f in rows]
        assert all(f > 0 for f in freqs)
        # frequency list must be sorted descending
        assert freqs == sorted(freqs, reverse=True)
        # no empty or whitespace words
        assert all(w.strip() for w, _ in rows)


def test_persuasive_list_has_argumentative_vocabulary():
    """The persuasive-genre list must contain characteristic items — a
    cheap content sanity check that the build pulled the right texts."""
    spec = _spec("pd-persuasive")
    words = {w for w, _ in _load_rows(spec)}
    assert {"government", "people", "reason", "rights"} <= words


def test_dialectal_list_is_genuinely_arabic_script():
    spec = _spec("dialectal-arabic-tweets")
    rows = _load_rows(spec)
    arabic = sum(1 for w, _ in rows if all("\u0621" <= ch <= "\u064A" for ch in w))
    assert arabic >= 900, "dialectal list should be (almost) entirely Arabic script"


def test_learner_list_differs_from_native_persuasive_list():
    """An ICLE-style reference exists to contrast with native English —
    its top vocabulary must not collapse onto the persuasive list's."""
    learner = {w for w, _ in _load_rows(_spec("ellipse-learner"))}
    persuasive = {w for w, _ in _load_rows(_spec("pd-persuasive"))}
    assert learner != persuasive
