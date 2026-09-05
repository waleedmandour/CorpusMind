"""Build the BAWE processed mirror ZIP (release asset ``reference-mirrors-v1``).

Why this exists
---------------
The Oxford Text Archive gateway routinely fails large bitstream requests
(HTTP 504 / hang) — the canonical BAWE URL is unreliable. BAWE is licensed
CC-BY-NC-SA-3.0, which permits redistribution **with attribution**, so
CorpusMind hosts a processed mirror (a ZIP of the first 500 assignment
texts, ~15 MB) as a GitHub release asset. The engine's full-corpus
pipeline tries that mirror BEFORE the canonical OTA URL and falls back
automatically.

BNC Baby is deliberately NOT mirrored — the BNC User Licence does not
permit redistribution.

Usage
-----
1. Download the original archive manually in a browser (browsers cope with
   the slow OTA gateway far better than raw HTTP clients):

   https://ota.bodleian.ox.ac.uk/repository/xmlui/bitstream/handle/20.500.12024/2539/2539.zip?sequence=3&isAllowed=y

2. Build the mirror ZIP:

   python scripts/build_bawe_mirror.py /path/to/2539.zip

3. Upload the produced file (default ``dist/bawe-sample-500.zip``) as the
   release asset, i.e. create or refresh the ``reference-mirrors-v1``
   release so the asset URL matches the one pinned in
   ``engine/reference_corpus/registry.py``::

       gh release create reference-mirrors-v1 dist/bawe-sample-500.zip \
           --title "Reference corpus mirrors" \
           --notes "Processed BAWE sample (500 assignments). CC-BY-NC-SA-3.0, attribution: Nesi et al. (2004-2008), Oxford Text Archive."
       # (or, if the release exists:)
       gh release upload reference-mirrors-v1 dist/bawe-sample-500.zip --clobber

4. Sanity-check the asset URL returns 200:

   curl -sIL https://github.com/waleedmandour/CorpusMind/releases/download/reference-mirrors-v1/bawe-sample-500.zip | head -1
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

DEFAULT_MAX_FILES = 500  # must match ReferenceCorpusSpec.max_files for bawe
TEXT_SUFFIXES = (".txt", ".xml")


def build_mirror(source_zip: Path, out_path: Path, max_files: int = DEFAULT_MAX_FILES) -> int:
    """Copy the first ``max_files`` .txt/.xml members (sorted by path) from
    the original BAWE archive into a flat, engine-ready mirror ZIP.

    Returns the number of files written.
    """
    if not source_zip.exists():
        raise SystemExit(f"Source archive not found: {source_zip}")
    with zipfile.ZipFile(source_zip) as zin:
        members = sorted(
            n for n in zin.namelist()
            if n.lower().endswith(TEXT_SUFFIXES) and not n.endswith("/")
        )
        if not members:
            raise SystemExit("Source archive contains no .txt/.xml members.")
        selected = members[:max_files]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for name in selected:
                zout.writestr(name, zin.read(name))
    return len(selected)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source_zip", type=Path, help="Path to the manually downloaded BAWE ZIP")
    ap.add_argument(
        "-o", "--output", type=Path,
        default=Path("dist/bawe-sample-500.zip"),
        help="Output mirror ZIP path (default: dist/bawe-sample-500.zip)",
    )
    ap.add_argument(
        "-n", "--max-files", type=int, default=DEFAULT_MAX_FILES,
        help=f"Number of documents to include (default: {DEFAULT_MAX_FILES})",
    )
    args = ap.parse_args()

    count = build_mirror(args.source_zip, args.output, args.max_files)
    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(f"Wrote {count} documents ({size_mb:.1f} MB) → {args.output}")
    print(
        "Next: upload it as the 'bawe-sample-500.zip' asset of the "
        "'reference-mirrors-v1' GitHub release (see module docstring)."
    )


if __name__ == "__main__":
    sys.exit(main())
