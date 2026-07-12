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

from pathlib import Path

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
    "magic",
    "lxml",
    "bs4",
    "docx",
    "pypdf",
    # Stats
    "numpy",
    "scipy",
    "statsmodels",
    "pingouin",
    # Storage
    "sqlalchemy",
    "aiosqlite",
    # Export
    "openpyxl",
    "reportlab",
    # Reproducibility
    "yaml",
]

# Data files to bundle (non-Python assets the engine reads at runtime).
# We include the reference-data/ directory so frameworks + wordlists ship
# inside the binary.
_datas = []
_repo_root = Path(SPECPATH).parent  # noqa: F821 — SPECPATH is provided by PyInstaller
_reference_data = _repo_root / "reference-data"
if _reference_data.exists():
    _datas.append((str(_reference_data), "reference-data"))

a = Analysis(
    ["app/main.py"],
    pathex=[SPECPATH],  # noqa: F821
    binaries=[],
    datas=_datas,
    hiddenimports=_hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim test / dev tooling from the bundle
        "pytest",
        "pytest-asyncio",
        "pytest-cov",
        "mypy",
        "ruff",
        "pip",
        "setuptools",
        "wheel",
        "IPython",
        "jupyter",
        "matplotlib",
        "tkinter",
        # Heavy ML packages not needed at runtime — cv2 is a lazy import
        # in vision/facial.py (opt-in Phase 5 feature). PIL is installed
        # separately and IS included.
        "cv2",
        "opencv-python",
        "sklearn",
        "scikit-learn",
        "pandas",
        "torch",
        "torchvision",
        "tensorflow",
        "keras",
        # Cairosvg (PNG export) — needs system libcairo which isn't available
        # on Windows. SVG export works without it.
        "cairosvg",
        "cairocffi",
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
    console=True,
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
