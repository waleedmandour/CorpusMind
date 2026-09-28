"""Release hygiene — engine __version__ must stay in lockstep across surfaces.

app/__init__.py documents that __version__ tracks engine/pyproject.toml, the
root package.json and desktop/src-tauri/tauri.conf.json. Nothing enforced it,
and it drifted twice already: silently across v1.2.7/v1.2.8, then again in the
first v1.2.10 build where the running app still displayed v1.2.9 in the UI
(/api/system reads app.__version__). These tests fail the release build the
moment any surface lags behind pyproject.
"""

import json
import tomllib
from pathlib import Path

from app import __version__

_ENGINE_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _ENGINE_ROOT.parent


def test_engine_version_matches_pyproject() -> None:
    pyproject = (_ENGINE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert tomllib.loads(pyproject)["project"]["version"] == __version__


def test_desktop_and_web_surfaces_match_engine_version() -> None:
    root_pkg = json.loads(
        (_REPO_ROOT / "package.json").read_text(encoding="utf-8")
    )
    web_pkg = json.loads(
        (_REPO_ROOT / "web" / "package.json").read_text(encoding="utf-8")
    )
    tauri = json.loads(
        (_REPO_ROOT / "desktop" / "src-tauri" / "tauri.conf.json").read_text(
            encoding="utf-8"
        )
    )
    assert root_pkg["version"] == __version__
    assert web_pkg["version"] == __version__
    assert tauri["version"] == __version__
