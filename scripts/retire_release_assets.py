#!/usr/bin/env python3
"""Retire installer assets from superseded CorpusMind releases.

Per the 2026-10-30 work order: every release except v2.0.0, v2.0.1 and
reference-mirrors-v1 is superseded. From superseded releases only the
INSTALLER assets (dmg/exe/msi/AppImage/deb) are deleted — user-guide PDFs,
web bundles, SHA256SUMS.txt and source archives stay. Superseded release
notes get an idempotent "superseded" banner.

DRY RUN IS THE DEFAULT: without --apply the script only writes a CSV manifest
(tag, asset, size_bytes, downloads, action) and prints the plan. Nothing is
deleted and no release notes are touched.

The canonical manifest is committed at docs/release_retirement_manifest.csv.
--apply is a REVIEWED, ONE-WAY operation: GitHub release-asset deletion is
IRREVERSIBLE (there is no trash/restore). Apply only once the manifest has
been reviewed and the docs+chore PR that introduces it has merged.

Usage:
    python scripts/retire_release_assets.py                  # dry run
    python scripts/retire_release_assets.py --csv plan.csv   # custom manifest
    python scripts/retire_release_assets.py --apply          # DO IT (explicit)

Auth: GITHUB_TOKEN / CORPUSMIND_GH_TOKEN env var, else the token embedded in
the origin remote URL (the local-clone pattern used by the other gh_*.py
scripts).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO_DEFAULT = "waleedmandour/CorpusMind"
KEEP_TAGS = {"v2.0.0", "v2.0.1", "reference-mirrors-v1"}
INSTALLER_EXTS = {".dmg", ".exe", ".msi", ".appimage", ".deb"}
BANNER_MARKER = "<!-- corpusmind:superseded-banner -->"
BANNER = (
    BANNER_MARKER + "\n"
    "> [!WARNING]\n"
    "> **Superseded release (assets retired).** The installer binaries in this\n"
    "> release were removed to free repository storage. For current installers,\n"
    "> see the [releases page]"
    "(https://github.com/waleedmandour/CorpusMind/releases/latest).\n"
)


def token() -> str:
    for var in ("CORPUSMIND_GH_TOKEN", "GITHUB_TOKEN"):
        val = os.environ.get(var, "").strip()
        if val:
            return val
    url = subprocess.run(
        ["git", "-C", os.path.dirname(os.path.abspath(__file__)) or ".", "remote", "get-url", "origin"],
        capture_output=True, text=True,
    )
    if url.returncode != 0:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"], capture_output=True, text=True
        )
    m = re.search(r"//(?:([^:@/]+):)?([^@/]+)@", url.stdout.strip())
    if m:
        return m.group(2) or m.group(1)
    sys.exit("no token: set GITHUB_TOKEN or use a tokened origin remote")


def api(tok: str, method: str, path: str, payload: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"https://api.github.com{path}" if path.startswith("/") else path,
        method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    return json.loads(body) if body else {}


def all_releases(tok: str, repo: str) -> list[dict]:
    out: list[dict] = []
    page = 1
    while True:
        rels = api(tok, "GET", f"/repos/{repo}/releases?per_page=100&page={page}")
        if not rels:
            break
        out.extend(rels)
        page += 1
        if page > 20:
            break
    return out


def is_installer(name: str) -> bool:
    return any(name.lower().endswith(ext) for ext in INSTALLER_EXTS)


def main() -> int:
    ap = argparse.ArgumentParser(description="Retire installer assets from superseded releases")
    ap.add_argument("--apply", action="store_true",
                    help="perform deletions and add banners (default: dry run)")
    ap.add_argument("--csv", default="docs/release_retirement_manifest.csv",
                    help="manifest path for the dry run (default: ./docs/release_retirement_manifest.csv)")
    ap.add_argument("--repo", default=REPO_DEFAULT)
    ap.add_argument("--keep", action="append", default=[],
                    help="additional tags to keep (repeatable)")
    ap.add_argument("--banner-only", action="store_true",
                    help="apply mode: add banners but do NOT delete assets")
    args = ap.parse_args()

    tok = token()
    keep = KEEP_TAGS | set(args.keep)
    releases = all_releases(tok, args.repo)
    print(f"fetched {len(releases)} releases from {args.repo}")

    deletions: list[dict] = []
    banners: list[dict] = []
    rows: list[dict] = []
    for rel in releases:
        tag = rel["tag_name"]
        superseded = tag not in keep
        for a in rel.get("assets", []):
            action = "keep"
            if superseded and is_installer(a["name"]):
                action = "delete"
                deletions.append({"tag": tag, "asset": a, "release": rel})
            elif superseded:
                action = "keep (not an installer)"
            rows.append({
                "tag": tag,
                "asset": a["name"],
                "size_bytes": a["size"],
                "downloads": a["download_count"],
                "action": action,
            })
        if superseded and BANNER_MARKER not in (rel.get("body") or ""):
            banners.append({"tag": tag, "release": rel})

    # ---- manifest (always written, dry run or not) ----
    with open(args.csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["tag", "asset", "size_bytes", "downloads", "action"])
        w.writeheader()
        w.writerows(rows)
    print(f"manifest written: {args.csv} ({len(rows)} asset rows)")

    freed = sum(d["asset"]["size"] for d in deletions)
    print(f"\nplan: {len(deletions)} installer assets to delete "
          f"({freed / 1e9:.2f} GB), {len(banners)} banners to add")
    if not args.apply:
        by_tag: dict[str, list[str]] = {}
        for d in deletions:
            by_tag.setdefault(d["tag"], []).append(d["asset"]["name"])
        for tag in sorted(by_tag):
            print(f"  {tag}: {len(by_tag[tag])} installers")
        print("\nDRY RUN — nothing deleted, no notes edited. Re-run with --apply to execute.")
        return 0

    # ---- apply ----
    if args.banner_only:
        print("banner-only mode: skipping asset deletions")
    ok = err = 0
    for d in deletions:
        if args.banner_only:
            break
        try:
            api(tok, "DELETE", f"/repos/{args.repo}/releases/assets/{d['asset']['id']}")
            ok += 1
            time.sleep(0.3)  # be gentle with the API
        except urllib.error.HTTPError as e:
            err += 1
            print(f"  DELETE failed {d['tag']}/{d['asset']['name']}: HTTP {e.code}")
    print(f"assets deleted: {ok}, failures: {err}")

    ok = err = 0
    for b in banners:
        body = BANNER + (b["release"].get("body") or "")
        try:
            api(tok, "PATCH", f"/repos/{args.repo}/releases/{b['release']['id']}",
                {"body": body})
            ok += 1
            time.sleep(0.3)
        except urllib.error.HTTPError as e:
            err += 1
            print(f"  BANNER failed {b['tag']}: HTTP {e.code}")
    print(f"banners added: {ok}, failures: {err}")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
