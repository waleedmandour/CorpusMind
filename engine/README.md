# CorpusMind Engine

This is the Python engine package of CorpusMind — a local-first, AI-native
research environment for corpus linguistics and multimodal discourse analysis.

For full documentation, architecture overview, quickstart, and release notes,
see the project root [README.md](../README.md) on GitHub:
https://github.com/waleedmandour/CorpusMind

## Quick install

```bash
cd engine
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python -m spacy download en_core_web_sm
```

> Note: this file intentionally lives inside `engine/` (rather than referencing
> `../README.md` from `pyproject.toml`) because build backends such as
> hatchling require the readme path to be within the project directory.
