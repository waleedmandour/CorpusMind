"""Write a manifest.json for a committed benchmark results snapshot.

The manifest is what makes a results snapshot reviewer-verifiable: it records
the workflow run URL, the exact commit the run tested, the UTC commit time,
and the sha256 + byte size of every artifact file, so any drift between the
paper's numbers and the repository is detectable.

Usage:
    python benchmarks/scripts/make_manifest.py benchmarks/results/run-123 \
        --run-url https://github.com/owner/repo/actions/runs/123 \
        --commit abc1234...
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description="Benchmark snapshot manifest")
    ap.add_argument("directory", type=Path)
    ap.add_argument("--run-url", required=True)
    ap.add_argument("--commit", required=True)
    args = ap.parse_args()

    files = []
    for p in sorted(args.directory.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            files.append({
                "path": str(p.relative_to(args.directory)),
                "sha256": _sha256(p),
                "bytes": p.stat().st_size,
            })

    # pull the provenance blocks the battery writes inside its own outputs
    meta: dict = {}
    perf = args.directory / "perf-arabic" / "perf_arabic.json"
    if not perf.exists():
        alt = args.directory / "perf_arabic.json"
        perf = alt if alt.exists() else perf
    if perf.exists():
        try:
            meta = json.loads(perf.read_text(encoding="utf-8")).get("_meta", {})
        except Exception:
            meta = {}

    manifest = {
        "run_url": args.run_url,
        "commit": args.commit,
        "utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "runner": {
            "platform": meta.get("platform"),
            "cpu_count": meta.get("cpu_count"),
            "python": meta.get("python"),
            "camel_tools": meta.get("camel_tools"),
        },
        "files": files,
    }
    dest = args.directory / "manifest.json"
    dest.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"[manifest] {dest} ({len(files)} files)")


if __name__ == "__main__":
    main()
