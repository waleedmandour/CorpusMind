#!/usr/bin/env python3
"""Install the license-restricted optional Persuasion Index resources.

The four data-backed resources of ``persuasion-index`` (concreteness x2,
LIWC, NRC-VAD) are never bundled with CorpusMind: their provider terms
forbid redistribution. persuasion-index resolves them through its own
``PI_*`` env vars; the engine (v1.2.9) bridges a single stable folder —
``<data_dir>/pi-resources/`` by default — onto those vars at startup.

This script arranges the official downloads into that folder:

  1. single-word concreteness (Brysbaert et al. 2014, .xlsx)
     - can be fetched directly from the publisher-hosted supplemental
       archive (``--all-open``), or placed manually (``--from <file>``);
  2. multiword-expression concreteness (.csv, Muraki et al. 2023, OSF)
     - direct fetch from the file's OSF GUID or the authors' GitHub
       mirror (``--all-open``) or ``--from``;
  3. NRC-VAD lexicon v2.1 unigrams
     - YOU download the official zip (the site requires agreement to the
       license terms), then ``--nrc-vad-zip <downloaded.zip>`` extracts
       the unigram file into the layout;
  4. LIWC dictionary
     - YOU own a license; ``--liwc-file <en_liwc.txt>`` copies your
       legacy .dic (LIWC-22 .dicx is NOT supported by PI 0.3.0).

Each direct download is content-checked (xlsx zip magic / CSV header) so
an HTML error or maintenance page is rejected instead of being installed
under the canonical filename.

Examples
--------
  # fetch the two openly downloadable concreteness files:
  python scripts/install_pi_resources.py --all-open

  # after downloading NRC-VAD v2.1 manually from saifmohammad.com:
  python scripts/install_pi_resources.py --nrc-vad-zip ~/Downloads/NRC-VAD-Lexicon-v2.1.zip

  # with a licensed LIWC 2007/2015-style dictionary:
  python scripts/install_pi_resources.py --liwc-file ~/licensed/en_liwc.dic

  # custom target folder (otherwise CORPUSMIND_PI_RESOURCES_DIR or
  # ~/.corpusmind/pi-resources):
  python scripts/install_pi_resources.py --all-open --dir /path/to/folder

After installing, restart the engine and re-check
``GET /api/v1/discourse/persuasion/health`` (or the in-app resource panel).

Requires no third-party packages for arranging files; the direct-fetch
mode uses only the standard library (urllib + zipfile).
"""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

# Official, publisher-hosted direct downloads for the two concreteness
# resources. NRC-VAD and LIWC are intentionally NOT auto-downloaded: the
# NRC site gates the download behind license agreement and LIWC requires
# a paid license — the user performs those downloads themselves.
DIRECT_FETCH = {
    "single_word_concreteness": {
        "filename": "Brysbaert_concretness_dataset.xlsx",
        "urls": [
            # Publisher (Springer) supplemental archive of the BRM 2014
            # article — verified to carry the Word / Conc.M columns
            # persuasion-index validates (39,954 rows). The Ghent
            # bibliographic page (biblio.ugent.be/publication/5774089) is
            # the paper's landing page but hosts only the article PDF, so
            # it is NOT a data source and its old direct-file URL 404s.
            "https://static-content.springer.com/esm/art%3A10.3758%2Fs13428-013-0403-5/MediaObjects/13428_2013_403_MOESM1_ESM.xlsx",
        ],
    },
    "multiword_concreteness": {
        "filename": "MultiwordExpression_Concreteness_Ratings.csv",
        "urls": [
            # The exact file on the authors' OSF project ksypa (GitHub
            # storage add-on; file GUID he4dv, verified via the OSF API).
            # NOTE: the project GUID itself (/download/ksypa/) does NOT
            # serve this file — the project's osfstorage root holds only
            # the rating-instructions .docx, so the old URL could never
            # yield the CSV.
            "https://osf.io/download/he4dv/",
            # Author's mirror of the same file (byte-identical size,
            # 2,995,806 B; Expression / Mean_C header).
            "https://raw.githubusercontent.com/ejmuraki/multiword-exp/master/MultiwordExpression_Concreteness_Ratings.csv",
        ],
    },
}


def content_ok(key: str, data: bytes) -> bool:
    """Cheap content gate for a freshly downloaded resource.

    Rejects HTML/error/maintenance pages (e.g. an OSF outage) before they
    can be saved under the canonical filename and look installed to the
    engine — the failure mode that motivated v1.2.15.
    """
    if key == "single_word_concreteness":
        # .xlsx is a zip archive: PK magic + the real file is ~2.2 MB.
        return data[:2] == b"PK" and len(data) > 100_000
    if key == "multiword_concreteness":
        first_line = data[:2048].lstrip(b"\xef\xbb\xbf").split(b"\n", 1)[0].strip()
        return first_line.startswith(b"Expression") and b"Mean_C" in first_line
    return False


def default_dir() -> Path:
    import os

    env = os.environ.get("CORPUSMIND_PI_RESOURCES_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    home = Path.home()
    return home / ".corpusmind" / "pi-resources"


def fetch_bytes(url: str) -> bytes | None:
    """Download url into memory. Returns None on any network/OS failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CorpusMind-pi-installer/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except Exception as exc:  # noqa: BLE001 — report any network/OS failure
        print(f"    ! {url}\n      {exc}")
        return None


def install_direct(target: Path, key: str) -> bool:
    spec = DIRECT_FETCH[key]
    dest = target / spec["filename"]
    if dest.is_file():
        print(f"[skip] {key}: {dest} already exists")
        return True
    print(f"[get ] {key} → {dest}")
    for url in spec["urls"]:
        print(f"    trying {url}")
        data = fetch_bytes(url)
        if data is None:
            continue
        if not content_ok(key, data):
            print(
                f"    ! downloaded bytes are not the expected data file "
                f"({len(data):,} B) — the host is serving an error or wrong "
                "page; trying the next source"
            )
            continue
        dest.write_bytes(data)
        print(f"    ok ({len(data):,} bytes)")
        return True
    print(
        "    ! all direct sources failed — download manually from the link in\n"
        "      the app's Persuasion Index resource panel (official source per\n"
        "      resource) and rerun with --from / --mwe-from."
    )
    return False


def install_from(target: Path, src: Path, filename: str, key: str) -> bool:
    if not src.is_file():
        print(f"[FAIL] {key}: {src} not found")
        return False
    dest = target / filename
    shutil.copyfile(src, dest)
    print(f"[ok  ] {key}: {src} → {dest}")
    return True


def install_nrc_vad_zip(target: Path, zip_path: Path) -> bool:
    wanted = Path("NRC-VAD-Lexicon-v2.1") / "Unigrams" / "unigrams-NRC-VAD-Lexicon-v2.1.txt"
    dest = target / wanted
    if not zip_path.is_file():
        print(f"[FAIL] NRC-VAD zip not found: {zip_path}")
        return False
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        member = next(
            (n for n in names if n.replace("\\", "/").endswith(wanted.as_posix())),
            None,
        )
        if member is None:
            # Also accept the flat layout some mirrors ship.
            member = next(
                (n for n in names if n.replace("\\", "/").endswith("unigrams-NRC-VAD-Lexicon-v2.1.txt")),
                None,
            )
        if member is None:
            print(f"[FAIL] {zip_path} does not contain {wanted.as_posix()}")
            print("       members: " + ", ".join(names[:12]) + (" …" if len(names) > 12 else ""))
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as fsrc, dest.open("wb") as fdst:
            shutil.copyfileobj(fsrc, fdst)
    print(f"[ok  ] nrc_vad: {zip_path} → {dest}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", help="target resources folder (default: $CORPUSMIND_PI_RESOURCES_DIR or ~/.corpusmind/pi-resources)")
    ap.add_argument("--all-open", action="store_true", help="directly fetch the two openly downloadable concreteness files")
    ap.add_argument("--from", dest="from_file", metavar="FILE", help="copy FILE as the single-word concreteness xlsx (explicit override)")
    ap.add_argument("--mwe-from", dest="mwe_from", metavar="FILE", help="copy FILE as the multiword concreteness csv")
    ap.add_argument("--nrc-vad-zip", dest="vad_zip", metavar="ZIP", help="extract the unigrams file from the official NRC-VAD v2.1 zip you downloaded")
    ap.add_argument("--liwc-file", dest="liwc", metavar="FILE", help="copy your licensed LIWC legacy .dic as en_liwc.txt")
    args = ap.parse_args()

    target = Path(args.dir).expanduser() if args.dir else default_dir()
    target.mkdir(parents=True, exist_ok=True)
    print(f"Resources folder: {target}")

    ok = True
    did = False
    if args.all_open:
        did = True
        for key in DIRECT_FETCH:
            ok = install_direct(target, key) and ok
    if args.from_file:
        did = True
        ok = install_from(target, Path(args.from_file).expanduser(), DIRECT_FETCH["single_word_concreteness"]["filename"], "single_word_concreteness") and ok
    if args.mwe_from:
        did = True
        ok = install_from(target, Path(args.mwe_from).expanduser(), DIRECT_FETCH["multiword_concreteness"]["filename"], "multiword_concreteness") and ok
    if args.vad_zip:
        did = True
        ok = install_nrc_vad_zip(target, Path(args.vad_zip).expanduser()) and ok
    if args.liwc:
        did = True
        ok = install_from(target, Path(args.liwc).expanduser(), "en_liwc.txt", "liwc") and ok
    if not did:
        ap.print_help()
        print("\nNothing to do: pass --all-open and/or the manual file options.")
        return 2

    print(
        "\nDone. Restart the CorpusMind engine, then re-open the Persuasion "
        "Index\nresource panel (or GET /api/v1/discourse/persuasion/health) to confirm."
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
