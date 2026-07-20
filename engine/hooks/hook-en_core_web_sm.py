"""
PyInstaller hook for the spaCy en_core_web_sm model.

Collects ALL files (Python + data) from the en_core_web_sm package so it
can be imported and loaded as a complete model inside the frozen exe.

Without this hook, PyInstaller's static analysis misses the model's binary
data (weights, vocab, tokenizer) because they're loaded at runtime via
spaCy's data-path resolution, not via static imports.
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = []
hiddenimports = []

try:
    # Collect ALL files (Python + data) — include_py_files=True is critical
    # because without __init__.py, the model isn't an importable package.
    datas += collect_data_files("en_core_web_sm", include_py_files=True)
    hiddenimports += collect_submodules("en_core_web_sm")
    # Also collect spacy itself's data files (linker data, etc.)
    datas += collect_data_files("spacy", include_py_files=False)
except Exception:
    # Model not installed — non-fatal
    pass
