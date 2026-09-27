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
from pathlib import Path

import pytest

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


def test_env_override_resolves_docker_layout(tmp_path, monkeypatch) -> None:
    """v1.2.10: CORPUSMIND_REFERENCE_DATA_DIR resolves before the walks.

    The self-hosted Docker image bakes reference-data at
    /app/reference-data — a location no site-packages-relative walk can
    find — so the resolver gained an explicit env candidate.
    """
    fake = tmp_path / "reference-data"
    fake.mkdir()
    monkeypatch.setenv("CORPUSMIND_REFERENCE_DATA_DIR", str(fake))
    assert resource_paths.reference_data_dir() == fake


def test_meipass_still_beats_env_override(tmp_path, monkeypatch) -> None:
    """Frozen bundles must always read their OWN collected data."""
    env_dir = tmp_path / "env-pack"
    env_dir.mkdir()
    meipass_pack = tmp_path / "bundle-pack" / "reference-data"
    meipass_pack.mkdir(parents=True)
    monkeypatch.setenv("CORPUSMIND_REFERENCE_DATA_DIR", str(env_dir))
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass_pack.parent), raising=False)
    assert resource_paths.reference_data_dir() == meipass_pack


def test_env_override_ignored_when_empty_or_missing(tmp_path, monkeypatch) -> None:
    """A bogus env path falls through to the normal walk candidates."""
    monkeypatch.setenv("CORPUSMIND_REFERENCE_DATA_DIR", str(tmp_path / "nowhere"))
    d = resource_paths.reference_data_dir()
    assert d.is_dir()  # resolved via the dev-layout walk, not the env var


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


# ---------------------------------------------------------------------------
# v1.2.10 release gate: the /health/resources spaCy probe must mirror the
# pipeline's real load paths. spacy.util.is_package (importlib) is blind to
# the PyInstaller bundle's collected package data, so a healthy desktop
# bundle reported spacy_model.en_core_web_sm=false and failed the release
# smoke gate. These tests pin the frozen-layout probe WITHOUT requiring the
# model (or spaCy) to be installed in the test environment.
# ---------------------------------------------------------------------------


def _make_frozen_model(tmp_path: Path, subdir: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lay out a fake collected model (meta.json) the way PyInstaller does."""
    model_dir = tmp_path / subdir / "en_core_web_sm"
    model_dir.mkdir(parents=True)
    (model_dir / "meta.json").write_text('{"name": "en_core_web_sm"}', encoding="utf-8")


def _no_importlib(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the importlib leg of the probe to report not-installed.

    Both 'spacy' and 'spacy.util' must be faked together: ``import
    spacy.util`` binds the PARENT module and resolves ``.util`` as a real
    attribute, so overriding sys.modules["spacy.util"] alone is a no-op.
    """
    import types

    fake_util = types.ModuleType("spacy.util")
    fake_util.is_package = staticmethod(lambda name: False)  # type: ignore[attr-defined]
    fake_spacy = types.ModuleType("spacy")
    fake_spacy.util = fake_util  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)
    monkeypatch.setitem(sys.modules, "spacy.util", fake_util)


def test_spacy_model_found_via_meipass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Frozen layout: sys._MEIPASS/en_core_web_sm with meta.json is loadable."""
    _make_frozen_model(tmp_path, "data", monkeypatch)
    _no_importlib(monkeypatch)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "data"), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "bin" / "python"), raising=False)
    assert resource_paths.spacy_model_available() is True


def test_spacy_model_found_via_internal_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """onedir layout: <exe_dir>/_internal/en_core_web_sm with meta.json."""
    _no_importlib(monkeypatch)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "bin" / "corpusmind-engine"), raising=False)
    _make_frozen_model(tmp_path / "bin", "_internal", monkeypatch)
    assert resource_paths.spacy_model_available() is True


def test_spacy_model_absent_everywhere_reports_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No importlib hit and no frozen data dir -> honest False."""
    _no_importlib(monkeypatch)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "bin" / "corpusmind-engine"), raising=False)
    assert resource_paths.spacy_model_available() is False


def test_spacy_model_importlib_hit_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real importable install reports True even with no bundle dirs."""
    import types

    fake_util = types.ModuleType("spacy.util")
    fake_util.is_package = staticmethod(lambda name: True)  # type: ignore[attr-defined]
    fake_spacy = types.ModuleType("spacy")
    fake_spacy.util = fake_util  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)
    monkeypatch.setitem(sys.modules, "spacy.util", fake_util)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "bin" / "corpusmind-engine"), raising=False)
    assert resource_paths.spacy_model_available() is True
