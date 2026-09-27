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
