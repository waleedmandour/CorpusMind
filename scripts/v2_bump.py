#!/usr/bin/env python3
"""v2.x version bump: assertion-guarded, idempotent.

v2.0.0 history: 1.2.14 -> 2.0.0 (31 replacements, atomic across all live
version surfaces). This revision: 2.0.1 -> 2.0.2 (release-what-was-measured,
MODE A: engine code identical to the frozen benchmark commit ee42bfa except
version constants).

Historical version references (CHANGELOG entries, "post-v2.0.1" comments,
historical comments like "v1.2.14-8 (r8 ...)", guide body notes, the README
Versioned-DOIs history line, benchmarks/results/**,
docs/release_retirement_manifest.csv, engine/eval/data/gold/grounding_gold.json)
are deliberately untouched. Fails loudly if any live surface is not in the
expected state, so a partial bump can never be committed.

Idempotent: re-running on an already-bumped tree is a no-op (exit 0).

Usage:
    python scripts/v2_bump.py --date 2026-11-01
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD, NEW = "2.0.1", "2.0.2"

_MONTHS = {
    "01": "jan", "02": "feb", "03": "mar", "04": "apr",
    "05": "may", "06": "jun", "07": "jul", "08": "aug",
    "09": "sep", "10": "oct", "11": "nov", "12": "dec",
}

# (relpath, old_template, new_template, expected_occurrences)
# Templates may contain {OLD} / {NEW} / {DATE} / {MONTH} literal tokens,
# resolved with the --date argument in main().
JOBS: list[tuple[str, str, str, int]] = [
    ("package.json", '"version": "{OLD}"', '"version": "{NEW}"', 1),
    ("web/package.json", '"version": "{OLD}"', '"version": "{NEW}"', 1),
    ("shared/package.json", '"version": "{OLD}"', '"version": "{NEW}"', 1),
    # Locks: every package-lock entry that pins the project's own packages.
    # Third-party entries (argparse ^2.0.1, color-convert ^2.0.1, ...) use
    # other shapes and are never touched.
    ("package-lock.json", '"version": "{OLD}"', '"version": "{NEW}"', 9),
    ("web/package-lock.json", '"version": "{OLD}"', '"version": "{NEW}"', 9),
    ("desktop/src-tauri/tauri.conf.json", '"version": "{OLD}"', '"version": "{NEW}"', 1),
    ("desktop/src-tauri/Cargo.toml", 'version = "{OLD}"', 'version = "{NEW}"', 1),
    # NOTE: no Cargo.lock is tracked in the repo (built fresh by cargo); the
    # project's own Cargo.lock entry therefore does not exist to bump.
    ("web/src/hooks/useEngineVersion.ts", 'FALLBACK_VERSION = "{OLD}"', 'FALLBACK_VERSION = "{NEW}"', 1),
    ("engine/pyproject.toml", 'version = "{OLD}"', 'version = "{NEW}"', 1),
    ("engine/app/__init__.py", '__version__ = "{OLD}"', '__version__ = "{NEW}"', 1),
    ("infra/docker-compose.yml", "corpusmind/engine:{OLD}", "corpusmind/engine:{NEW}", 1),
    ("scripts/generate_user_guide_pdf.py", "v{OLD}: bumped alongside the engine version lockstep.", "v{NEW}: bumped alongside the engine version lockstep.", 1),
    ("scripts/generate_arabic_guide_pdf.py", "v{OLD}: bumped alongside the engine version lockstep.", "v{NEW}: bumped alongside the engine version lockstep.", 1),
    # CITATION.cff: top-level version AND the indented preferred-citation
    # version (both contain the substring), plus BOTH date-released values.
    ("CITATION.cff", "version: {OLD}", "version: {NEW}", 2),
    ("CITATION.cff", "date-released: 2026-10-30", "date-released: {DATE}", 2),
    # README: badge, current-release line, language-support line, health-check
    # sample, plain-text citation, BibTeX version and month.
    # The Versioned-DOIs history line (v2.0.1 -> 10.5281/zenodo.23785435) is
    # historical and intentionally NOT matched by any template.
    ("README.md", "release-v{OLD}-blue", "release-v{NEW}-blue", 1),
    ("README.md", "**Current release: v{OLD}**", "**Current release: v{NEW}**", 1),
    ("README.md", "**Language support (v{OLD}):**", "**Language support (v{NEW}):**", 1),
    ("README.md", '"version":"{OLD}"', '"version":"{NEW}"', 1),
    ("README.md", "(Version {OLD})", "(Version {NEW})", 1),
    ("README.md", "version      = {2.0.1},", "version      = {2.0.2},", 1),
    ("README.md", "month        = oct,", "month        = {MONTH},", 1),
    # Guides: header + Zenodo citation line ONLY (body mentions stay historical).
    ("docs/USER_GUIDE.md", "> Version {OLD} | AGPL-3.0-only", "> Version {NEW} | AGPL-3.0-only", 1),
    ("docs/USER_GUIDE.md", "analysis* (Version {OLD}) [Computer software]", "analysis* (Version {NEW}) [Computer software]", 1),
    ("docs/USER_GUIDE_AR.md", "> الإصدار {OLD} | رخصة AGPL-3.0", "> الإصدار {NEW} | رخصة AGPL-3.0", 1),
    ("docs/USER_GUIDE_AR.md", "analysis* (Version {OLD}) [Computer software]", "analysis* (Version {NEW}) [Computer software]", 1),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="CorpusMind v2.0.1 -> v2.0.2 bump (assertion-guarded, idempotent)")
    parser.add_argument("--date", required=True, help="release date YYYY-MM-DD for CITATION.cff date-released")
    args = parser.parse_args()
    date: str = args.date
    if len(date) != 10 or date[4] != "-" or date[7] != "-":
        raise SystemExit(f"FAIL --date must be YYYY-MM-DD, got {date!r}")
    month = _MONTHS[date[5:7]]
    subs = {"{OLD}": OLD, "{NEW}": NEW, "{DATE}": date, "{MONTH}": month}

    def render(t: str) -> str:
        for token, value in subs.items():
            t = t.replace(token, value)
        return t

    # Idempotency: if NO live surface still carries OLD but NEW is present in
    # the first job's file, the bump was already applied — no-op.
    old_found = False
    for rel, old_t, _new_t, _expected in JOBS:
        old = render(old_t)
        if old in (ROOT / rel).read_text(encoding="utf-8"):
            old_found = True
            break
    probe = (ROOT / JOBS[0][0]).read_text(encoding="utf-8")
    if not old_found and render('"version": "{NEW}"') in probe:
        print(f"Already at {NEW} — nothing to do (idempotent no-op).")
        return

    applied = 0
    for rel, old_t, new_t, expected in JOBS:
        old = render(old_t)
        new = render(new_t)
        p = ROOT / rel
        text = p.read_text(encoding="utf-8")
        n = text.count(old)
        if n != expected:
            raise SystemExit(f"FAIL {rel}: expected {expected}x {old!r}, found {n}")
        p.write_text(text.replace(old, new), encoding="utf-8")
        applied += expected
        print(f"OK {rel}: {n} replacement(s)")
    print(f"\nApplied {applied} replacements across {len(JOBS)} jobs.")

    # Post-conditions: no live surface still carries the old version. The two
    # guides are checked header/citation-only: their body text keeps
    # historical version mentions by design, and CHANGELOG history is never
    # rewritten.
    live = [
        "package.json", "web/package.json", "shared/package.json",
        "desktop/src-tauri/tauri.conf.json", "desktop/src-tauri/Cargo.toml",
        "web/src/hooks/useEngineVersion.ts",
        "engine/pyproject.toml", "engine/app/__init__.py",
        "infra/docker-compose.yml",
        "scripts/generate_user_guide_pdf.py", "scripts/generate_arabic_guide_pdf.py",
    ]
    stale: list[str] = []
    for rel in live:
        text = (ROOT / rel).read_text(encoding="utf-8")
        if OLD in text:
            stale.append(rel)
    # Lockfiles: third-party packages legitimately use version 2.0.1
    # (argparse, color-convert, ...) — only the project's OWN entries carry
    # the exact '"version": "2.0.1"' pin, and those must all have moved.
    for rel in ("package-lock.json", "web/package-lock.json"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        if f'"version": "{OLD}"' in text:
            stale.append(rel)
    # useEngineVersion.ts keeps HISTORICAL comments like "v1.2.14-3 (PWA
    # hotfix)" by design — only the live FALLBACK_VERSION must have moved.
    hook = (ROOT / "web/src/hooks/useEngineVersion.ts").read_text(encoding="utf-8")
    if f'FALLBACK_VERSION = "{OLD}"' in hook:
        stale.append("web/src/hooks/useEngineVersion.ts (live FALLBACK_VERSION)")
    stale = [s for s in stale if s != "web/src/hooks/useEngineVersion.ts"]
    cff = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    if f"version: {OLD}" in cff or "date-released: 2026-10-30" in cff:
        stale.append("CITATION.cff")
    for rel in ("docs/USER_GUIDE.md", "docs/USER_GUIDE_AR.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        if f"> Version {OLD}" in text or f"> الإصدار {OLD}" in text or f"(Version {OLD}) [Computer software]" in text:
            stale.append(rel)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for snippet in (f"release-v{OLD}-blue", f"Current release: v{OLD}", f"(Version {OLD})"):
        if snippet in readme:
            stale.append("README.md")
    if stale:
        raise SystemExit(f"FAIL stale surfaces still mention {OLD}: {sorted(set(stale))}")
    print("Post-condition: no live surface carries the old version.")


if __name__ == "__main__":
    main()
