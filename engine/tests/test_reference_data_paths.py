"""Regression tests for reference-data resolution (v1.2.8, review #1).

The PyInstaller bundle collects ``reference-data/`` under ``sys._MEIPASS``
while a dev checkout keeps it two parents above any engine module. The
packaged v1.2.8 release shipped with the USAS lens 503ing because the old
hardcoded ``dirname(__file__)/../..`` walk only knew the dev layout. These
tests pin BOTH layouts so the packaged engine and a dev checkout can never
drift apart again.
"""

from __future__ import annotations

import sys

from app import resource_paths


def setup_function() -> None:
    resource_paths.reference_data_dir.cache_clear()


def teardown_function() -> None:
    resource_paths.reference_data_dir.cache_clear()


def test_dev_layout_resolves_to_repo_reference_data() -> None:
    """Without _MEIPASS the resolver walks to the repo root layout."""
    d = resource_paths.reference_data_dir()
    assert d.is_dir()
    assert d.name == "reference-data"
    # The repo actually ships these files — a dev engine must find them.
    assert (d / "tagsets" / "usas-en-top.tsv").exists()
    assert (d / "tagsets" / "usas-ar-top.tsv").exists()
    assert (d / "wordlists" / "awl-sublists.tsv").exists()


def test_meipass_layout_wins_when_frozen(tmp_path, monkeypatch) -> None:
    """Inside the bundle, sys._MEIPASS/reference-data must be preferred."""
    fake = tmp_path / "reference-data"
    (fake / "tagsets").mkdir(parents=True)
    (fake / "tagsets" / "usas-en-top.tsv").write_text(
        "lemma\ttag\nhello\tA\n", encoding="utf-8"
    )
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert resource_paths.reference_data_dir() == fake
    assert resource_paths.resource_path("tagsets", "usas-en-top.tsv") == (
        fake / "tagsets" / "usas-en-top.tsv"
    )


def test_load_semantic_lexicon_uses_meipass_layout(tmp_path, monkeypatch) -> None:
    """The USAS lexicon loader must read through the frozen layout too."""
    from nlp.tagsets import load_semantic_lexicon

    fake = tmp_path / "reference-data"
    (fake / "tagsets").mkdir(parents=True)
    (fake / "tagsets" / "usas-en-top.tsv").write_text(
        "lemma\ttag\nhouse\tH\n", encoding="utf-8"
    )
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    load_semantic_lexicon.cache_clear()
    try:
        assert load_semantic_lexicon("en") == {"house": "H"}
    finally:
        load_semantic_lexicon.cache_clear()
        monkeypatch.undo()


def test_load_semantic_lexicon_dev_layout_nonempty() -> None:
    """Sanity: the committed lexicon loads and lookup works in a dev run."""
    from nlp.tagsets import load_semantic_lexicon, semantic_lookup

    load_semantic_lexicon.cache_clear()
    try:
        lex = load_semantic_lexicon("en")
        assert lex, "committed usas-en-top.tsv must load in dev layout"
        probe_lemma = next(iter(lex))
        assert semantic_lookup(probe_lemma, probe_lemma, "en") == lex[probe_lemma]
    finally:
        load_semantic_lexicon.cache_clear()


def test_exists_never_raises_when_reference_data_missing(tmp_path, monkeypatch) -> None:
    """exists() reports False instead of raising when nothing resolves."""
    # Point every candidate at an empty temp dir: no reference-data anywhere.
    monkeypatch.setattr(resource_paths, "_candidates", lambda: (tmp_path / "nowhere",))
    resource_paths.reference_data_dir.cache_clear()
    try:
        assert resource_paths.exists("tagsets", "usas-en-top.tsv") is False
    finally:
        resource_paths.reference_data_dir.cache_clear()
        monkeypatch.undo()
