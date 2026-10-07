# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the CorpusMind engine sidecar.

Builds a one-directory (onedir) distribution that the Tauri desktop shell
spawns as a child process. The executable listens on 127.0.0.1:8765 by
default (overridable via CORPUSMIND_HOST / CORPUSMIND_PORT env vars).

We use onedir mode (not onefile) because:
  1. On Windows, onefile mode is extremely slow (3+ hours) because Windows
     Defender scans every file as it's being compressed into the single EXE.
  2. Onedir startup is faster (no extraction to temp dir on each run).
  3. Tauri can bundle the directory as a resource.

Build:
    cd engine
    pyinstaller corpusmind-engine.spec --noconfirm

Output:
    dist/corpusmind-engine/corpusmind-engine          (Linux/macOS)
    dist/corpusmind-engine/corpusmind-engine.exe      (Windows)
    dist/corpusmind-engine/_internal/                  (all deps)

The Tauri bundler copies the entire directory into the app's resources.
See:
    desktop/src-tauri/src/lib.rs  ->  resolve_command()
"""
from __future__ import annotations

import sys

from pathlib import Path

# PyInstaller utilities for collecting a package's data files + submodules.
# Used below to bundle the spaCy `en_core_web_sm` model's package data
# (weights, vocab, tokenizer config, etc.) — not just the `spacy` framework.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Hidden imports that PyInstaller's static analysis misses (dynamic imports,
# entry-point plugins, lazy-loaded optional deps).
_hidden_imports = [
    "uvicorn.logging",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    # FastAPI / Pydantic internals
    "pydantic._internal._validators",
    "email_validator",
    # spaCy pipeline components (loaded by string name at runtime)
    "spacy",
    "spacy.pipeline",
    "spacy.language",
    "spacy.tokenizer",
    # Note: spacy.lemmatizer was removed in spaCy 3.5+ — do not include it
    # File parsers
    # NOTE: 'magic' (python-magic) is NOT included — it requires the native
    # libmagic DLL which is not available on Windows. The engine uses file
    # extensions for format detection (ingestion/parsing.py:detect_format),
    # not libmagic. Including it causes PyInstaller to crash on Windows with
    # "Isolated subprocess crashed while importing package 'magic'" (exit code
    # 3221226505 = STATUS_DLL_NOT_FOUND).
    "lxml",
    "bs4",
    "docx",
    "pypdf",
    # Stats
    "numpy",
    "scipy",
    # Collocation-network graph assembly (api/network.py)
    "networkx",
    # NOTE: statsmodels + pingouin removed — never used (grep confirmed zero
    # imports). They transitively pull in pandas — removing all three reduces
    # bundle size and DLL load-time risk.
    # Storage
    "sqlalchemy",
    "aiosqlite",
    # Export
    "openpyxl",
    "reportlab",
    # Reproducibility
    "yaml",
    # Issue 8/1: missing hidden imports that caused features to be broken
    # in the desktop app. These are all imported by the engine but PyInstaller's
    # static analysis missed them (lazy imports, entry-point plugins).
    "langdetect",             # ingestion/service.py — auto-detect corpus language
    "charset_normalizer",     # ingestion/parsing.py — detect file encoding
    "PIL",                    # multimodal/alignment.py, vision/facial.py — image processing
    "PIL.Image",              # PIL sub-module used explicitly
    "PIL.ImageFilter",        # PIL sub-module used explicitly
    "tenacity",               # retry logic (transitive dep, not guaranteed)
    "anyio",                  # FastAPI/uvicorn async runtime
    "structlog",              # app/logging.py
    "websockets",             # uvicorn WebSocket support
    "pydantic_settings",      # app/settings.py
    "httpx",                  # AI provider HTTP client + Arabic data installer
    "multipart",              # FastAPI form data parsing (python-multipart)
    "charset_normalizer.md",  # charset_normalizer sub-module
    # v1.2.11 follow-up: the DIDModel6 dialect-ID stack (belt-and-braces —
    # static analysis finds these through camel_tools.dialectid.model6, but
    # kenlm is a top-level compiled .so from the camel_kenlm wheel and dill
    # unpickles the model, so both are pinned explicitly).
    "kenlm",
    "dill",
    # v1.2.8 (review #6): persuasion-index stack. The package's public API
    # is imported LAZILY (persuasion_index/__init__ uses import_module), so
    # PyInstaller's static analysis cannot see the real modules — they must
    # be listed explicitly. The wheel also ships top-level companion
    # modules (persuasion_profile, persuasion_runner, PI_score_generator,
    # pi_config, helper_features) that are imported by bare module name.
    # Hard deps of the wheel: pandas (imported at api.py import time),
    # wordfreq (ships msgpack data files — collected below),
    # vaderSentiment; numpy is already a hidden import above.
    "persuasion_index",
    "persuasion_index.api",
    "persuasion_index.cli",
    "persuasion_index.resources",
    "persuasion_index.liwc",
    "persuasion_profile",
    "persuasion_runner",
    "PI_score_generator",
    "pi_config",
    "pandas",
    "wordfreq",
    "vaderSentiment",
    "vaderSentiment.vaderSentiment",
]

# Data files to bundle (non-Python assets the engine reads at runtime).
# We include the reference-data/ directory so frameworks + wordlists ship
# inside the binary.
_datas = []
_repo_root = Path(SPECPATH).parent  # noqa: F821 — SPECPATH is provided by PyInstaller
_reference_data = _repo_root / "reference-data"
if _reference_data.exists():
    _datas.append((str(_reference_data), "reference-data"))

# v1.2.8 (review #6): pull in the persuasion-index package's own data
# (bundled lexicons), the helper_features submodules, and wordfreq's
# per-language frequency data. NOTE: this block MUST come after `_datas`
# is initialised — an earlier placement raised NameError inside the broad
# except below, silently dropping the collected data (the Windows content
# gate caught the empty wordfreq data dir). Guarded like en_core_web_sm: a
# build venv without the package still produces a bundle, and the release
# smoke gate fails the release if the stack ends up missing.
try:
    _hidden_imports += collect_submodules("helper_features")
    _hidden_imports += collect_submodules("persuasion_index")
    _hidden_imports += collect_submodules("wordfreq")
    _datas += collect_data_files("persuasion_index")
    _datas += collect_data_files("wordfreq")
except Exception:
    # persuasion-index not installed in this build venv — non-fatal here,
    # but the release smoke gate will refuse to publish such a bundle.
    pass

# Bundle the spaCy `en_core_web_sm` model as a COMPLETE package (Python files
# + data files). PyInstaller's static analysis picks up the model package via
# collect_submodules, but collect_data_files with include_py_files=False only
# collects the data files, not the __init__.py — so the model can't be
# imported as a package at runtime. Using include_py_files=True ensures the
# model is a fully importable package, which our fallback __import__() in
# pipeline.py relies on.
try:
    _datas += collect_data_files("en_core_web_sm", include_py_files=True)
    _hidden_imports += collect_submodules("en_core_web_sm")
except Exception:
    # Model not installed in this build venv — non-fatal. The engine will still
    # build and run; NLP ingestion just won't work until the model is present.
    pass

# --------------------------------------------------------------------------- #
# v1.2.11 (Arabic Tools hang fix): bundle the CAMeL Tools stack so Arabic
# Tools can work offline.
#
# Two parts:
#   1. camel_tools CODE + PACKAGE data (char tables for Buckwalter /
#      dediacritization). collect_data_files is required: camel_tools ships
#      non-Python data inside the package that static analysis misses.
#      This part is ALWAYS collected — it is small and license-clean
#      (camel_tools is MIT).
#   2. the MANAGED data pack (calima-msa-r13 morphology DB ~39MB raw +
#      dialectid model6 ~122MB raw). v1.2.11 follow-up: bundling this pack
#      is now OPT-IN at build time via
#          CORPUSMIND_BUNDLE_CAMEL_DATA=1
#      Default builds DO NOT ship the pack (it is GPL-2.0-only data, and
#      keeping it out of the default distribution avoids the redistribution
#      obligations entirely). An unprovisioned app returns an actionable
#      HTTP 503 for Arabic analysis, and the in-app Arabic data pack
#      installer (Settings, or the button in the 503 card) downloads the
#      pinned pack into the user's data directory with size + SHA256
#      verification. When the flag IS set at build time, the pack is
#      provisioned on the build machine via `camel_data -i` into
#      ~/.camel_tools and collected verbatim as camel-tools-data/. At
#      runtime nlp.arabic.pipeline pins CAMELTOOLS_DATA to this directory
#      (app/resource_paths.py) BEFORE importing camel_tools, so the frozen
#      app resolves its own copy and never touches the network.
#
# NOTE: torch (a hard camel-tools dependency) stays EXCLUDED below — the
# morphology analyzer and DIDModel6 paths are non-neural (verified: no
# torch/transformers import in the loaded module set). Installing camel-tools
# in the build venv requires torch to be present to satisfy pip; install the
# CPU wheel first in the release workflow.
# --------------------------------------------------------------------------- #
try:
    _hidden_imports += collect_submodules("camel_tools")
    _datas += collect_data_files("camel_tools")
except Exception:
    # camel-tools not installed in this build venv — non-fatal here (dev
    # builds); the release smoke gate refuses to publish such a bundle.
    pass
import os as _os  # noqa: E402 — placed here to keep the bundle block together

if _os.environ.get("CORPUSMIND_BUNDLE_CAMEL_DATA", "").strip() == "1":
    _ct_home = Path.home() / ".camel_tools"
    if (_ct_home / "catalogue.json").is_file():
        _datas.append((str(_ct_home), "camel-tools-data"))
        print("[spec] CORPUSMIND_BUNDLE_CAMEL_DATA=1 -> bundling camel-tools-data/")
    else:
        print(
            "[spec] WARNING: CORPUSMIND_BUNDLE_CAMEL_DATA=1 but no provisioned "
            "pack at ~/.camel_tools (run: camel_data -i morphology-db-msa-r13 "
            "&& camel_data -i dialectid-model6). Building WITHOUT the data "
            "pack; the release smoke gate will fail unless the installer-only "
            "mode is intended."
        )
else:
    print(
        "[spec] CORPUSMIND_BUNDLE_CAMEL_DATA not set -> NOT bundling the "
        "camel-tools data pack (default; the in-app installer covers it)"
    )

# --------------------------------------------------------------------------- #
# v1.2.9 Student Mode (classroom server) bundle additions.
#
# 1. web-dist: the built PWA (repo web/dist) is collected into the bundle so
#    the Caddy sidecar can serve student browsers from disk. CI builds the
#    web PWA BEFORE the engine for this reason. A dev build without a web
#    dist just skips this (Student Mode then refuses to enable with a clear
#    teacher-readable error, and everything else keeps working).
# 2. caddy: the pinned Caddy reverse-proxy binary (fetched by
#    scripts/fetch_caddy.py into engine/caddy-bin/, gitignored) is collected
#    as a raw binary under caddy/. Without it Student Mode cannot enable —
#    the release smoke gates now hard-fail on a missing classroom stack.
# --------------------------------------------------------------------------- #
_binaries = []
_web_dist = _repo_root / "web" / "dist"
if (_web_dist / "index.html").is_file():
    _datas.append((str(_web_dist), "web-dist"))

_caddy_bin_dir = Path(SPECPATH) / "caddy-bin"  # noqa: F821
_caddy_exe = "caddy.exe" if sys.platform.startswith("win") else "caddy"
_caddy_src = _caddy_bin_dir / _caddy_exe
if _caddy_src.is_file():
    _binaries.append((str(_caddy_src), "caddy"))

a = Analysis(
    ["app/main.py"],
    pathex=[SPECPATH],  # noqa: F821
    binaries=_binaries,
    datas=_datas,
    hiddenimports=_hidden_imports,
    hookspath=[str(Path(SPECPATH) / "hooks")],  # noqa: F821 — custom hooks dir
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim test / dev tooling from the bundle
        "pytest",
        "pytest-asyncio",
        "pytest-cov",
        "mypy",
        "ruff",
        # NOTE: pip, setuptools, and wheel must NOT be excluded —
        # `pip install -e .` imports them during installation, and
        # PyInstaller crashes with "Target module 'wheel' already
        # imported as ExcludedModule('wheel',)" if they're in excludes.
        "IPython",
        "jupyter",
        "matplotlib",
        "tkinter",
        # python-magic requires the native libmagic DLL which is not available
        # on Windows. The engine uses file extensions for format detection,
        # not libmagic, so we exclude it to avoid the PyInstaller crash:
        # "Isolated subprocess crashed while importing package 'magic'"
        "magic",
        # Heavy ML packages not needed at runtime — cv2 is a lazy import
        # in vision/facial.py (opt-in Phase 5 feature). PIL is installed
        # separately and IS included.
        "cv2",
        "opencv-python",
        # v1.2.11 follow-up: sklearn (scikit-learn) is NOT excluded any
        # more — camel_tools' DIDModel6 dialect-ID model is a pickled
        # sklearn pipeline (MultinomialNB / TfidfVectorizer / LabelEncoder).
        # With the old exclusion the frozen bundle silently degraded the
        # dialect route to the lexicon heuristic ("No module named
        # 'sklearn'"); the smoke gate now asserts real city-level scores.
        # NOTE: "pandas" was removed from this exclude list in v1.2.8
        # (review #6) — persuasion_index.api imports pandas at module
        # scope, so excluding it crashed the Persuasion Index lens inside
        # the packaged engine. torch/tensorflow/keras stay excluded: the
        # engine has no runtime use for them.
        "torch",
        "torchvision",
        "tensorflow",
        "keras",
        # Issue 3: cairosvg is NO LONGER excluded — it's needed for PNG export
        # of collocation network diagrams. On Windows it may fail at runtime
        # if libcairo isn't installed, but SVG export (which doesn't need
        # cairosvg) still works. The engine handles this gracefully with a
        # try/except in api/export.py:_svg_to_png().
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# onedir mode: much faster to build than onefile (no compression into single
# file), faster startup (no extraction to temp dir), and works well with
# Tauri's resource bundling.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="corpusmind-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # console=False: hide the console window on Windows. The engine's stdout/
    # stderr are still captured by the Tauri shell (via Stdio::from() in the
    # Rust spawn() call), so "Run Diagnostics" in Settings still shows the logs.
    # With console=True, a visible terminal window appears alongside the app,
    # which is confusing for end users and must be kept open or the engine dies.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="corpusmind-engine",
)
