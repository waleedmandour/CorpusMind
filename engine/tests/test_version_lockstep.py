"""Release hygiene — engine __version__ must stay in lockstep across surfaces.

app/__init__.py documents that __version__ tracks engine/pyproject.toml, the
root package.json and desktop/src-tauri/tauri.conf.json. Nothing enforced it,
and it drifted three times: silently across v1.2.7/v1.2.8, again in the
first v1.2.10 build where the running app still displayed v1.2.9 in the UI
(/api/system reads app.__version__), and at v1.2.11 prep the root
package-lock, shared package and docker tag were found stale. These tests
fail the release build the moment any surface lags behind pyproject.

v1.2.11 coverage: + shared/package.json, desktop Cargo.toml, both npm
package-locks, CITATION.cff (version + preferred-citation), the frontend
engine-version fallback (useEngineVersion.ts), the docker-compose image tag,
and the two User Guide PDF generator scripts (so a guide can never be
regenerated against the wrong version without failing CI).

v1.2.14 metadata truth-up coverage: the cff version check now also matches
the indented preferred-citation version (it previously escaped the
top-level-only regex), plus four README guards — release badge, "Current
release" line, README DOI vs cff DOI, and the claimed backend test count
(never overstated against the static def count).
"""

import json
import re
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


def test_shared_package_matches_engine_version() -> None:
    shared = json.loads(
        (_REPO_ROOT / "shared" / "package.json").read_text(encoding="utf-8")
    )
    assert shared["version"] == __version__


def test_npm_locks_match_engine_version() -> None:
    for rel in ("package-lock.json", "web/package-lock.json"):
        lock = json.loads((_REPO_ROOT / rel).read_text(encoding="utf-8"))
        assert lock["version"] == __version__, f"{rel} root version"
        assert lock["packages"][""]["version"] == __version__, f"{rel} packages[''] version"


def test_desktop_cargo_manifest_matches_engine_version() -> None:
    cargo = (_REPO_ROOT / "desktop" / "src-tauri" / "Cargo.toml").read_text(
        encoding="utf-8"
    )
    m = re.search(r'^version\s*=\s*"([^"]+)"', cargo, flags=re.M)
    assert m, "Cargo.toml [package] version not found"
    assert m.group(1) == __version__


def test_citation_cff_matches_engine_version() -> None:
    cff = (_REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8")
    versions = re.findall(r"^\s*version:\s*(\S+)", cff, flags=re.M)
    assert versions, "CITATION.cff has no version field"
    assert all(v == __version__ for v in versions), versions


def test_frontend_engine_version_fallback_matches() -> None:
    hook = (_REPO_ROOT / "web" / "src" / "hooks" / "useEngineVersion.ts").read_text(
        encoding="utf-8"
    )
    m = re.search(r'FALLBACK_VERSION\s*=\s*"([^"]+)"', hook)
    assert m, "useEngineVersion FALLBACK_VERSION not found"
    assert m.group(1) == __version__


def test_docker_compose_image_tag_matches_engine_version() -> None:
    compose = (_REPO_ROOT / "infra" / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    m = re.search(r"image:\s*corpusmind/engine:([^\s\"]+)", compose)
    assert m, "docker-compose engine image tag not found"
    assert m.group(1) == __version__


def test_user_guide_pdf_scripts_target_engine_version() -> None:
    """The release pipeline rejects a guide whose version does not match the
    tag — this test is the in-repo enforcement: both guide generators must
    carry the engine version, and the filenames they emit must embed it."""
    for script in (
        "scripts/generate_user_guide_pdf.py",
        "scripts/generate_arabic_guide_pdf.py",
    ):
        text = (_REPO_ROOT / script).read_text(encoding="utf-8")
        hits = re.findall(rf'v?{re.escape(__version__)}', text)
        assert hits, f"{script} does not reference the engine version {__version__}"


def test_readme_release_badge_matches_engine_version() -> None:
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"release-v([0-9.]+)-blue", readme)
    assert m, "README release badge not found"
    assert m.group(1) == __version__


def test_readme_current_release_line_matches() -> None:
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert f"Current release: v{__version__}" in readme


def test_readme_doi_matches_cff_doi() -> None:
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    cff = (_REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8")
    m = re.search(r'value:\s*"(10\.[^"]+)"', cff)
    assert m, "CITATION.cff has no DOI identifier"
    cff_doi = m.group(1)
    assert (
        cff_doi in readme.replace("%2F", "/")
        or cff_doi.replace("/", "%2F") in readme
    )


def test_readme_test_count_not_overstated() -> None:
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"(\d+)\+ backend test functions", readme)
    if m:
        actual = sum(
            1
            for p in (_ENGINE_ROOT / "tests").glob("test_*.py")
            for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("def test_")
        )
        assert int(m.group(1)) <= actual
