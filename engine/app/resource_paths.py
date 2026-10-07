"""Robust reference-data location for dev checkouts AND the PyInstaller bundle.

The repo keeps non-code resources (USAS tagsets, wordlists, bundled
reference corpora, sentiment lexicons) at the repository root under
``reference-data/``. In a dev checkout every engine module can reach it by
walking two parents up (``engine/<pkg>/<mod>.py`` -> repo root). In the
packaged desktop app (PyInstaller onedir) that walk lands ONE level too
high: Python modules live under ``<app>/_internal/...`` while data files
are collected into ``<app>/_internal/reference-data`` — so
``dirname(__file__)/../../reference-data`` resolved to
``<app>/reference-data``, which does not exist.

That was the root cause of the v1.2.8 "The USAS semantic lexicon for 'en'
is not installed" 503 (review #1) and of the silently degraded Academic
Word List / bundled reference lists.

``reference_data_dir()`` resolves candidates in order and caches the first
that exists:

  1. ``sys._MEIPASS`` / reference-data — PyInstaller (onedir and onefile)
  2. ``CORPUSMIND_REFERENCE_DATA_DIR`` / reference-data — explicit override
     (v1.2.10): used by the self-hosted Docker image, which bakes
     ``reference-data/`` at ``/app/reference-data`` — a location no
     site-packages-relative walk can find. Also lets labs mount a custom
     data pack without rebuilding the image.
  3. repo root via the module's parents — dev checkout / source runs
  4. one-parent walk                   — alternative frozen layouts

Every consumer of ``reference-data/`` MUST go through this helper so the
packaged engine and a dev checkout behave identically.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path


def _candidates() -> tuple[Path, ...]:
    """Resolution candidates, best first (kept pure for testability)."""
    seen: list[Path] = []
    # 1. PyInstaller: data files are collected under sys._MEIPASS.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        seen.append(Path(meipass) / "reference-data")
    # 2. Explicit override (v1.2.10): the Docker image sets
    #    CORPUSMIND_REFERENCE_DATA_DIR=/app/reference-data; labs can point
    #    it at a mounted custom data pack.
    env_dir = os.environ.get("CORPUSMIND_REFERENCE_DATA_DIR", "").strip()
    if env_dir:
        seen.append(Path(env_dir))
    # 3. Dev checkout / source run: engine/app/../../reference-data.
    here = Path(__file__).resolve().parent
    seen.append(here.parent.parent / "reference-data")
    # 4. Alternative frozen layouts where modules sit beside the data.
    seen.append(here.parent / "reference-data")
    unique: list[Path] = []
    for c in seen:
        if c not in unique:
            unique.append(c)
    return tuple(unique)


@lru_cache(maxsize=1)
def reference_data_dir() -> Path:
    """Absolute path to the ``reference-data/`` directory.

    Raises FileNotFoundError when no candidate exists so callers can
    choose between a hard failure and a documented fallback.
    """
    for candidate in _candidates():
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        "reference-data directory not found (searched: "
        + ", ".join(str(c) for c in _candidates())
        + ")"
    )


def resource_path(*parts: str) -> Path:
    """Path inside reference-data, e.g. ``resource_path("tagsets", "usas-en-top.tsv")``."""
    return reference_data_dir().joinpath(*parts)


# --------------------------------------------------------------------------- #
# CAMeL Tools managed data (v1.2.11, Arabic Tools hang fix)
#
# camel_tools resolves its managed data directory at IMPORT time: the
# ``CAMELTOOLS_DATA`` env var if set, else ``~/.camel_tools`` (see
# ``camel_tools.data.catalogue.CT_DATA_DIR``). When its catalogue file is
# MISSING, ``MorphologyDB.builtin_db()`` transparently launches a BLOCKING,
# TIMEOUT-LESS HTTPS download (``Catalogue.update_catalogue()`` ->
# ``requests.Session().get(url, stream=True)`` with no timeout) — on an
# offline or firewalled machine that call never returns. Because the Arabic
# routes ran this synchronously on the event loop, the whole engine froze and
# the Arabic Tools panel spun forever (the reported "Analysis never finishes").
#
# The fix has two halves:
#   1. THIS resolver: find the data directory in every supported layout
#      (env override / PyInstaller bundle / dev home) WITHOUT any network IO,
#      and put the bundled copy on the env var before camel_tools is imported.
#   2. ``nlp.arabic.pipeline`` pre-flights the catalogue file and raises an
#      actionable error instead of letting camel_tools attempt a download.
# --------------------------------------------------------------------------- #

_CAMEL_BUNDLE_SUBDIR = "camel-tools-data"
_CAMEL_CATALOGUE_MARKER = "catalogue.json"


def _camel_bundle_candidates() -> tuple[Path, ...]:
    """Frozen-layout candidates for the bundled camel-tools data pack."""
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / _CAMEL_BUNDLE_SUBDIR)
    # onedir layout: data collected next to the launcher under _internal/.
    candidates.append(
        Path(os.path.dirname(os.path.abspath(sys.executable))) / "_internal" / _CAMEL_BUNDLE_SUBDIR
    )
    return tuple(candidates)


@lru_cache(maxsize=1)
def camel_tools_data_dir() -> Path | None:
    """Locate the CAMeL Tools managed-data directory, or return ``None``.

    Resolution order (first candidate containing ``catalogue.json`` wins):

      1. ``CAMELTOOLS_DATA`` — camel_tools' own env override; respected so an
         operator can point the engine at a shared, pre-provisioned pack.
      2. the PyInstaller-bundled pack (``camel-tools-data/`` collected by the
         spec from the build machine's ``~/.camel_tools``);
      3. ``~/.camel_tools`` — the developer default populated by
         ``camel_data -i morphology-db-msa-r13`` (+ ``dialectid-model6``).

    ``None`` means "not provisioned on this machine" — callers MUST refuse
    fast with an actionable message; they must NEVER fall back to camel_tools'
    built-in download-at-first-use behaviour (that is the indefinite hang).
    """
    env_dir = os.environ.get("CAMELTOOLS_DATA", "").strip()
    if env_dir and (Path(env_dir) / _CAMEL_CATALOGUE_MARKER).is_file():
        return Path(env_dir)
    for candidate in _camel_bundle_candidates():
        if (candidate / _CAMEL_CATALOGUE_MARKER).is_file():
            return candidate
    home_dir = Path.home() / ".camel_tools"
    if (home_dir / _CAMEL_CATALOGUE_MARKER).is_file():
        return home_dir
    return None


def camel_tools_bundle_available() -> bool:
    """True when a bundled/dev camel-tools data pack can be pinned via env.

    Used by ``nlp.arabic.pipeline`` BEFORE importing camel_tools so the
    frozen bundle's copy wins over a (possibly missing) ``~/.camel_tools``.
    """
    return camel_tools_data_dir() is not None


def exists(*parts: str) -> bool:
    """True when the referenced resource exists (never raises)."""
    try:
        return resource_path(*parts).exists()
    except FileNotFoundError:
        return False


def spacy_model_available(name: str = "en_core_web_sm") -> bool:
    """Report whether the spaCy ``name`` model can ACTUALLY be loaded here.

    v1.2.10 release-gate finding: ``spacy.util.is_package`` (importlib) is
    blind inside a PyInstaller bundle — the model ships as collected
    package data under ``sys._MEIPASS`` / ``<exe_dir>/_internal`` (with
    ``meta.json``), where ``spacy.load(model_dir)`` works (pipeline
    strategy 3, see ``nlp/general/pipeline.py``) but importlib does not
    resolve the package. A healthy desktop bundle therefore reported
    ``spacy_model.en_core_web_sm: false`` and failed the release smoke
    gate even though the model was present and loadable.

    This probe mirrors the pipeline's real load strategies instead:
      1. importlib — normal dev/venv/conda installs;
      2. the frozen bundle's data directories (meta.json present),
         exactly what strategy 3 scans.
    No cache: cheap filesystem checks, and callers may want live truth.
    """
    try:
        import spacy.util

        if spacy.util.is_package(name):
            return True
    except Exception:
        pass

    candidates: list[str] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, name))
    # onedir layout: data collected next to the launcher under _internal/.
    candidates.append(
        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "_internal", name)
    )
    for candidate in candidates:
        if os.path.isfile(os.path.join(candidate, "meta.json")):
            return True
    return False
