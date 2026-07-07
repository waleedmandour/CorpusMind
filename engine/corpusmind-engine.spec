# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the CorpusMind engine sidecar.

Builds a single-file (onefile) executable that the Tauri desktop shell spawns
as a child process. The binary listens on 127.0.0.1:8765 by default (overridable
via CORPUSMIND_HOST / CORPUSMIND_PORT env vars).

Build:
    cd engine
    pyinstaller corpusmind-engine.spec --noconfirm

Output:
    dist/corpusmind-engine              (Linux/macOS)
    dist/corpusmind-engine.exe          (Windows)

The Tauri bundler renames it to `corpusmind-engine-<target-triple>` and places
it in the app's resources directory at install time. See:
    desktop/src-tauri/src/lib.rs  ->  resolve_command()
"""
from __future__ import annotations

from pathlib import Path

block_cipher = None

# Engine package roots that must be collected as packages (not just imported).
# These are the top-level packages defined in pyproject.toml.
_engine_packages = [
    "app",
    "api",
    "ingestion",
    "nlp",
    "stats",
    "discourse",
    "vision",
    "multimodal",
    "ai",
    "storage",
]

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
    "spacy.lemmatizer",
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
        "mypy",
        "ruff",
        "pip",
        "setuptools",
        "wheel",
        "IPython",
        "jupyter",
        "matplotlib",
        "tkinter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# one-file build: faster startup for a long-running server, smaller disk
# footprint, and matches the Tauri sidecar model (single binary dropped into
# resources/).
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="corpusmind-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,  # keep debug symbols for crash logs
    upack=False,  # UPX breaks code signing on macOS — disabled
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # engine logs go to stderr; Tauri redirects to a file
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # build for the host arch (arm64 on Apple Silicon)
    codesign_identity=None,  # sign separately in CI / notarize step
    entitlements_file=None,
)
