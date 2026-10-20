#!/usr/bin/env python3
"""v1.2.14 stable bump: 1.2.14-11 -> 1.2.14 (assertion-guarded, 21 replacements).

Promotes the 1.2.14 line to stable: every live version surface drops the
semver pre-release suffix. Historical version references (CHANGELOG entries,
guide body notes like "shipped since v1.2.14-10", earlier pre-release guide
PDFs in download/) are deliberately untouched — the guides are checked
header/citation-only. Fails loudly if any surface is not in the expected
state, so a partial bump can never be committed.

Note: CITATION.cff date-released stays 2026-10-20 (already set by r11).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD, NEW = "1.2.14-11", "1.2.14"

# (relpath, old_snippet, new_snippet, expected_occurrences)
JOBS: list[tuple[str, str, str, int]] = [
    ("package.json", f'"version": "{OLD}"', f'"version": "{NEW}"', 1),
    ("web/package.json", f'"version": "{OLD}"', f'"version": "{NEW}"', 1),
    ("shared/package.json", f'"version": "{OLD}"', f'"version": "{NEW}"', 1),
    # Locks: root version + packages[""] + workspace entries.
    ("package-lock.json", f'"version": "{OLD}"', f'"version": "{NEW}"', 4),
    ("web/package-lock.json", f'"version": "{OLD}"', f'"version": "{NEW}"', 2),
    ("desktop/src-tauri/tauri.conf.json", f'"version": "{OLD}"', f'"version": "{NEW}"', 1),
    ("desktop/src-tauri/Cargo.toml", f'version = "{OLD}"', f'version = "{NEW}"', 1),
    ("web/src/hooks/useEngineVersion.ts", f'FALLBACK_VERSION = "{OLD}"', f'FALLBACK_VERSION = "{NEW}"', 1),
    ("CITATION.cff", f"version: {OLD}", f"version: {NEW}", 1),
    ("engine/pyproject.toml", f'version = "{OLD}"', f'version = "{NEW}"', 1),
    ("engine/app/__init__.py", f'__version__ = "{OLD}"', f'__version__ = "{NEW}"', 1),
    ("infra/docker-compose.yml", f"corpusmind/engine:{OLD}", f"corpusmind/engine:{NEW}", 1),
    ("scripts/generate_user_guide_pdf.py", f"v{OLD}: bumped alongside the engine version lockstep.", f"v{NEW}: bumped alongside the engine version lockstep.", 1),
    ("scripts/generate_arabic_guide_pdf.py", f"v{OLD}: bumped alongside the engine version lockstep.", f"v{NEW}: bumped alongside the engine version lockstep.", 1),
    # Guides: header + Zenodo citation line ONLY (body mentions stay historical).
    ("docs/USER_GUIDE.md", f"> Version {OLD} | AGPL-3.0-only", f"> Version {NEW} | AGPL-3.0-only", 1),
    ("docs/USER_GUIDE.md", f"analysis* (Version {OLD}) [Computer software]", f"analysis* (Version {NEW}) [Computer software]", 1),
    ("docs/USER_GUIDE_AR.md", f"> الإصدار {OLD} | رخصة AGPL-3.0", f"> الإصدار {NEW} | رخصة AGPL-3.0", 1),
    ("docs/USER_GUIDE_AR.md", f"analysis* (Version {OLD}) [Computer software]", f"analysis* (Version {NEW}) [Computer software]", 1),
]


def main() -> None:
    # Pre-condition: CITATION.cff date-released must already be today's
    # stable-release date (r11 set it); assert rather than modify.
    cff = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    if "date-released: 2026-10-20" not in cff:
        raise SystemExit("FAIL CITATION.cff: expected date-released: 2026-10-20")

    applied = 0
    for rel, old, new, expected in JOBS:
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
    # historical pre-release mentions (e.g. "recognized since v1.2.14-10")
    # by design, and CHANGELOG history is never rewritten.
    live = [
        "package.json", "web/package.json", "shared/package.json",
        "package-lock.json", "web/package-lock.json",
        "desktop/src-tauri/tauri.conf.json", "desktop/src-tauri/Cargo.toml",
        "web/src/hooks/useEngineVersion.ts", "CITATION.cff",
        "engine/pyproject.toml", "engine/app/__init__.py",
        "infra/docker-compose.yml",
        "scripts/generate_user_guide_pdf.py", "scripts/generate_arabic_guide_pdf.py",
    ]
    stale = []
    for rel in live:
        text = (ROOT / rel).read_text(encoding="utf-8")
        if OLD in text:
            stale.append(rel)
    for rel in ("docs/USER_GUIDE.md", "docs/USER_GUIDE_AR.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        if f"> Version {OLD}" in text or f"> الإصدار {OLD}" in text or f"(Version {OLD}) [Computer software]" in text:
            stale.append(rel)
    if stale:
        raise SystemExit(f"FAIL stale surfaces still mention {OLD}: {stale}")
    print("Post-condition: no live surface carries the old version.")


if __name__ == "__main__":
    main()
