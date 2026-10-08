"""In-app Arabic data pack installer (v1.2.11 follow-up).

Background: the desktop bundle no longer ships the CAMeL Tools data pack by
default (it is GPL-2.0-only data; see THIRD_PARTY_LICENSES.md). Arabic
analysis on an unprovisioned machine answers 503 with a hint. This module is
the in-app path out of that state: ONE user-initiated background job that
downloads the pinned pack from CAMeL Lab's official GitHub releases, verifies
it, and installs it into the resolved data directory.

Design contract (mirrors the engine's Arabic hard rules):

  - USER-INITIATED ONLY. The analysis request path never downloads anything
    (see nlp/arabic/pipeline.py::_require_camel_data). This job runs only
    when the user clicks Install.
  - PINNED SOURCES. Package URLs and SHA256 digests are frozen below and
    verified against the OBSERVED release assets (msa + dialectid:
    2026-10-07; egy/glf/lev dialect DBs: 2026-10-08, each zip downloaded,
    hashed, and its structure/licence verified - root morphology.db + LICENSE
    layout identical to the proven msa pack, licences match
    THIRD_PARTY_LICENSES.md: egy GPL-2.0-only, glf/lev CC BY 4.0). All three
    dialect zips show the SAME upstream re-upload drift as msa (exactly +214
    bytes vs the catalogue snapshot, differing zip-level digest) - the third
    independent proof that the code-pinned digest, not the catalogue's stale
    metadata, must be the verification authority. URL changes are a HARD
    error - a moved package is a new supply chain and must ship as a new
    engine release.
  - BOUNDED NETWORK. Every HTTP call uses explicit connect AND read
    timeouts (httpx.Timeout), so a firewalled machine fails in seconds,
    not forever. Progress is reported per chunk; a cancel request is
    honoured between chunks (cooperative cancel - a download in flight
    stops at the next chunk boundary).
  - SAFE INSTALL. Each package is downloaded to a temp file, verified,
    extracted to a staging directory, and only then moved into place
    (existing directory replaced atomically-ish via rename). versions.json
    is updated after each package so camel_tools' own catalogue bookkeeping
    stays consistent (camel_data -l sees the same state).
  - ONE JOB AT A TIME. A second install request gets 409.

Install target resolution (camel_tools_data_dir() order is respected at
analysis time via the env pin, so the installer writes where the engine
will later READ):
  1. CAMELTOOLS_DATA env var (operator override), if set
  2. ~/.camel_tools (camel_tools' own default; always writable)
The PyInstaller bundle dir is deliberately NOT a target: a packaged app's
resource directory is read-only on macOS/Windows and wiped on update.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx

from app.logging import get_logger
from app.resource_paths import reference_data_dir, refresh_camel_tools_data_dir

log = get_logger(__name__)

# Network bounds: connect fails fast; read applies BETWEEN bytes, so a slow
# but alive connection keeps working while a blackholed one dies in seconds.
# Read per-call (not at import) so tests can tighten them via env monkeypatch.
def _connect_timeout_s() -> float:
    import os

    return float(os.environ.get("CORPUSMIND_ARABIC_INSTALL_CONNECT_TIMEOUT_S", "10"))


def _read_timeout_s() -> float:
    import os

    return float(os.environ.get("CORPUSMIND_ARABIC_INSTALL_READ_TIMEOUT_S", "60"))


_CHUNK = 256 * 1024

# v1.2.11: the dialect morphology DBs the installer can now provision.
# These map 1:1 to the UI's dialect dropdown (pipeline._CAMEL_DIALECT_DBS
# minus the always-pinned MSA).
_DIALECT_DB_PACKAGES = frozenset(
    {
        "morphology-db-egy-r13",
        "morphology-db-glf-01",
        "morphology-db-lev-01",
    }
)


class ArabicInstallerError(RuntimeError):
    """Fatal installer problem (network, checksum, disk). Surfaces in the
    job's ``error`` field and the status endpoint."""


def _load_catalogue_snapshot() -> dict[str, Any]:
    """Load the pinned catalogue snapshot shipped in reference-data.

    Raises ArabicInstallerError (never FileNotFoundError) so the job can
    surface a clean message if the engine's reference-data is broken.
    """
    try:
        path = reference_data_dir() / "camel" / "catalogue-1.6.json"
        with path.open("r", encoding="utf-8") as fp:
            cat: dict[str, Any] = json.load(fp)
    except FileNotFoundError as e:
        raise ArabicInstallerError(
            "The Arabic data pack catalogue snapshot is missing from this "
            "installation (reference-data/camel/catalogue-1.6.json)."
        ) from e
    except json.JSONDecodeError as e:
        raise ArabicInstallerError(
            "The Arabic data pack catalogue snapshot is corrupt."
        ) from e
    if cat.get("version", "").startswith("1.6") is False:
        raise ArabicInstallerError(
            f"Unexpected catalogue snapshot version: {cat.get('version')!r} "
            "(expected 1.6.x)."
        )
    return cat


def catalog_packages() -> list[dict[str, Any]]:
    """The packages the installer manages, in install order: the MSA
    morphology DB first (analysis works with just it), then the Egyptian /
    Gulf / Levantine dialect DBs (v1.2.11: the installer fetches these too -
    before this change the UI's dialect dropdown offered DBs nothing could
    provision), then the dialect-ID model last (the largest optional one).

    URLs + SHA256 digests below are the RELEASE-VERIFIED pins, checked
    against the actual release assets on 2026-10-07 (msa, dialectid) and
    2026-10-08 (egy, glf, lev - see module docstring for the verification).
    The shipped catalogue snapshot supplies url/destination/version/license;
    its own sha256/size metadata is advisory and a mismatch is logged, not
    fatal (the catalogue has shipped stale metadata; the observed asset
    digest is the pin).
    """
    cat = _load_catalogue_snapshot()
    out: list[dict[str, Any]] = []
    pinned = {
        # (url, sha256, size) verified against the LIVE release assets
        # 2026-10-07 (msa asset re-uploaded upstream; content diffed identical
        # to a fresh `camel_data -i` install; dialectid sha matches the
        # catalogue byte-for-byte, catalogue size metadata stale by ~1.8KB).
        "morphology-db-msa-r13": (
            "https://github.com/CAMeL-Lab/camel-tools-data/releases/download/2022.03.21/morphology_db_calima-msa-r13-0.4.0.zip",
            "fe6531250c5529307627cc63ed56447cbb9968020d6ea3ab867e6ad9af94c738",
            40488532,
        ),
        # v1.2.11: dialect morphology DBs, observed 2026-10-08. All three
        # show the same +214-byte re-upload drift as msa (catalogue-level
        # digest/size stale, zip content structurally identical to the msa
        # layout: root morphology.db + LICENSE).
        "morphology-db-egy-r13": (
            "https://github.com/CAMeL-Lab/camel-tools-data/releases/download/2022.03.21/morphology_db_calima-egy-r13-0.2.0.zip",
            "eb8a2d3a115cad819a808931e7fb941d54344096e563643ba742708892e862ac",
            67255921,
        ),
        "morphology-db-glf-01": (
            "https://github.com/CAMeL-Lab/camel-tools-data/releases/download/2022.03.30/morphology_db_calima-glf-01-0.1.0.zip",
            "385a29aa4737335d6431768546aaaf7ecf848dfd4bef460c7e3358168c73c9b3",
            7977135,
        ),
        "morphology-db-lev-01": (
            "https://github.com/CAMeL-Lab/camel-tools-data/releases/download/2022.05.30/morphology_db_calima-lev-01-0.1.0.zip",
            "34f012383f18196554ec38ec1d4e6c8d1cc767b25e00c397cd36c67afaf4c3c4",
            10622164,
        ),
        "dialectid-model6": (
            "https://github.com/CAMeL-Lab/camel-tools-data/releases/download/2026.06.08/dialectid_model6-1.1.2.zip",
            "579258f6fad13df92a24251c5d68a4495c24c132f3970cb745855191d66613c5",
            127877916,
        ),
    }
    order = (
        "morphology-db-msa-r13",
        "morphology-db-egy-r13",
        "morphology-db-glf-01",
        "morphology-db-lev-01",
        "dialectid-model6",
    )
    for name in order:
        pkg = cat["packages"].get(name)
        if pkg is None or pkg.get("private"):
            raise ArabicInstallerError(f"Catalogue snapshot is missing public package {name!r}.")
        pin_url, pin_sha, pin_size = pinned[name]
        if pkg.get("url") != pin_url:
            log.warning(
                "arabic_installer_catalogue_drift",
                package=name,
                snapshot_url=pkg.get("url"),
                pinned_url=pin_url,
            )
            raise ArabicInstallerError(
                f"Catalogue snapshot URL for {name!r} does not match the "
                "release-pinned URL. Refusing to install from an unpinned "
                "source; update the engine."
            )
        if pkg.get("sha256") != pin_sha:
            # Informational: the catalogue metadata has shipped stale before
            # (verified 2026-10-07). The code-pinned digest stays authoritative.
            log.warning(
                "arabic_installer_catalogue_stale_metadata",
                package=name,
                snapshot_sha=pkg.get("sha256"),
                pinned_sha=pin_sha,
            )
        out.append(
            {
                "name": name,
                "url": pin_url,
                "sha256": pin_sha,
                "size": pin_size,
                "destination": pkg["destination"],
                "version": pkg.get("version", ""),
                "license": pkg.get("license", "unknown"),
            }
        )
    return out


def _resolve_target_dir() -> Path:
    """Where to install. CAMELTOOLS_DATA wins; else ~/.camel_tools.

    The bundle directory is intentionally excluded (read-only on packaged
    apps, wiped on update) - see module docstring.
    """
    import os

    env_dir = os.environ.get("CAMELTOOLS_DATA", "").strip()
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".camel_tools"


def _package_state(target: Path, pkg: dict[str, Any]) -> str:
    """installed / missing for one package in the CURRENT data dir."""
    data_dir = target / "data" / pkg["destination"]
    return "installed" if data_dir.is_dir() else "missing"


def _versions_path(target: Path) -> Path:
    return target / "versions.json"


def _write_versions(target: Path, pkg_name: str, version: str) -> None:
    """Merge one package into versions.json (camel_tools bookkeeping)."""
    path = _versions_path(target)
    try:
        versions = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (json.JSONDecodeError, OSError):
        versions = {}
    versions[pkg_name] = version
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(versions, indent=4), encoding="utf-8")
    return None


class _Sha256Stream:
    """File wrapper that hashes while writing, so the digest is computed on
    the fly (no second 128MB read pass)."""

    def __init__(self, fp: Any) -> None:
        self._fp = fp
        self._hash = hashlib.sha256()
        self.bytes_written = 0

    def write(self, data: bytes) -> int:
        n = int(self._fp.write(data))
        self._hash.update(data)
        self.bytes_written += n
        return n

    def hexdigest(self) -> str:
        return self._hash.hexdigest()


class ArabicDataInstaller:
    """One-shot background job with progress, cancel and bounded network IO.

    State machine: idle -> running -> done | error | cancelled.
    The worker runs in a plain thread (sync httpx); the event loop only
    touches the small, lock-protected status dict.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._status: dict[str, Any] = {"state": "idle"}
        self._last_error: str | None = None

    # ------------------------------------------------------------------ #
    # Status surface (lock-protected; safe from the event loop)
    # ------------------------------------------------------------------ #

    def status(self) -> dict[str, Any]:
        with self._lock:
            s = dict(self._status)
            s["busy"] = s.get("state") == "running"
            if self._status.get("state") == "error" and self._last_error:
                s.setdefault("error", self._last_error)
            return s

    def _update(self, **fields: Any) -> None:
        with self._lock:
            self._status.update(fields)

    # ------------------------------------------------------------------ #
    # Job control
    # ------------------------------------------------------------------ #

    def start(
        self,
        include_dialect_id: bool = True,
        include_dialects: bool = True,
    ) -> dict[str, Any]:
        """Start an install job. Returns the immediate status snapshot.

        ``include_dialects`` (v1.2.11) also downloads the Egyptian / Gulf /
        Levantine morphology DBs - the dialect dropdown cannot analyze those
        dialects without them. ``include_dialect_id`` keeps controlling the
        (larger) dialect-ID model. Both default to True: one click must fix
        every data-driven 503 the UI can produce.

        Raises ArabicInstallerError with a user-readable message when the
        request cannot even start (already running, nothing to do, no
        writable target). HTTP layer maps those to 409/503.
        """
        with self._lock:
            if self._status.get("state") == "running" and self._thread and self._thread.is_alive():
                raise ArabicInstallerError("An Arabic data pack install is already running.")
            target = _resolve_target_dir()
            try:
                target.mkdir(parents=True, exist_ok=True)
                probe = target / ".corpusmind-write-probe"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
            except OSError as e:
                raise ArabicInstallerError(
                    f"The Arabic data directory is not writable: {target} ({e}). "
                    "Set CAMELTOOLS_DATA to a writable directory and restart."
                ) from e
            packages = catalog_packages()
            wanted = [
                p
                for p in packages
                if (p["name"] != "dialectid-model6" or include_dialect_id)
                and (p["name"] not in _DIALECT_DB_PACKAGES or include_dialects)
            ]
            pending = [p for p in wanted if _package_state(target, p) == "missing"]
            if not pending:
                raise ArabicInstallerError(
                    "The Arabic data pack is already installed (nothing to download)."
                )

            self._cancel.clear()
            self._last_error = None
            total_bytes = sum(p["size"] for p in pending)
            self._status = {
                "state": "running",
                "target_dir": str(target),
                "packages_total": len(pending),
                "packages_done": 0,
                "current_package": pending[0]["name"],
                "stage": "downloading",
                "bytes_done": 0,
                "bytes_total": total_bytes,
                "started_at": time.time(),
                "finished_at": None,
                "error": None,
                "installed": [],
                "source": "pinned-snapshot(catalogue-1.6.json)",
            }
            self._thread = threading.Thread(
                target=self._run,
                args=(target, pending),
                name="arabic-data-installer",
                daemon=True,
            )
            self._thread.start()
        # status() re-acquires the (non-reentrant) lock: call it OUTSIDE the
        # with-block above or start() deadlocks against itself.
        return self.status()

    def cancel(self) -> dict[str, Any]:
        """Request cooperative cancel. Takes effect between chunks/stages."""
        self._cancel.set()
        with self._lock:
            if self._status.get("state") == "running":
                self._status["stage"] = "cancelling"
            s = dict(self._status)
        s["busy"] = s.get("state") == "running"
        return s

    # ------------------------------------------------------------------ #
    # Worker (its own thread; sync code only)
    # ------------------------------------------------------------------ #

    def _run(self, target: Path, pending: list[dict[str, Any]]) -> None:
        done_bytes = 0
        installed: list[str] = []
        try:
            timeout = httpx.Timeout(
                connect=_connect_timeout_s(),
                read=_read_timeout_s(),
                write=_read_timeout_s(),
                pool=_connect_timeout_s(),
            )
            # Write catalogue.json FIRST: it is the marker the engine's
            # resolver keys on, and it is what makes the install visible to
            # /health/resources once the first package lands. The resolver
            # is lru_cached - on a clean first-run machine it already cached
            # None (the pre-install request or a health poll), so without
            # the refresh below the pack would stay invisible to every
            # request in this process and analysis would 503 forever
            # (v1.2.11-rc1: "cannot analyze after installing the pack").
            cat = _load_catalogue_snapshot()
            self._check_cancel()
            (target / "catalogue.json").write_text(json.dumps(cat), encoding="utf-8")
            refresh_camel_tools_data_dir()

            with httpx.Client(follow_redirects=True, timeout=timeout) as client:
                for idx, pkg in enumerate(pending):
                    self._check_cancel()
                    self._update(current_package=pkg["name"], stage="downloading")
                    log.info(
                        "arabic_installer_package_start",
                        package=pkg["name"],
                        size=pkg["size"],
                        url=pkg["url"],
                    )
                    done_bytes = self._download_and_install(client, target, pkg, done_bytes)
                    installed.append(pkg["name"])
                    _write_versions(target, pkg["name"], pkg["version"])
                    # A package just landed on disk: drop the cached
                    # resolution so pre-flight and /health/resources see it
                    # WITHOUT an app restart.
                    refresh_camel_tools_data_dir()
                    self._update(
                        packages_done=idx + 1,
                        bytes_done=done_bytes,
                        installed=installed,
                    )
                    log.info("arabic_installer_package_done", package=pkg["name"])

            self._update(state="done", stage="done", finished_at=time.time())
            log.info("arabic_installer_done", target=str(target), installed=installed)
        except _JobCancelledError:
            self._cleanup_partial(target, pending)
            # Cleanup may have REMOVED partial state; re-resolve from disk.
            refresh_camel_tools_data_dir()
            self._update(state="cancelled", stage="idle", finished_at=time.time())
            log.info("arabic_installer_cancelled", installed=installed)
        except Exception as e:
            self._cleanup_partial(target, pending)
            refresh_camel_tools_data_dir()
            self._last_error = f"{type(e).__name__}: {e}" if not isinstance(e, ArabicInstallerError) else str(e)
            self._update(state="error", stage="idle", finished_at=time.time(), error=self._last_error)
            log.warning("arabic_installer_failed", error=self._last_error)

    def _download_and_install(
        self, client: httpx.Client, target: Path, pkg: dict[str, Any], done_bytes: int
    ) -> int:
        """Download -> verify size+SHA256 -> unzip to staging -> move into
        place. Returns the running byte total. Cancellation is checked
        between chunks."""
        staging_root = target / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        tmp_zip = staging_root / f"{pkg['name']}.zip.part"
        hasher: _Sha256Stream | None = None
        try:
            with client.stream("GET", pkg["url"]) as resp:
                resp.raise_for_status()
                declared = int(resp.headers.get("content-length", "0") or 0)
                if declared and declared != pkg["size"]:
                    raise ArabicInstallerError(
                        f"{pkg['name']}: server reports {declared} bytes but the "
                        f"pinned size is {pkg['size']}. Nothing was installed. "
                        "The upstream file may have changed: CAMeL Lab has "
                        "re-uploaded release assets before without changing the "
                        "URL. Check your connection and retry; if it fails again, "
                        "report it so the pinned digest can be updated in a new "
                        "engine release."
                    )
                with tmp_zip.open("wb") as fp:
                    hasher = _Sha256Stream(fp)
                    for chunk in resp.iter_bytes(_CHUNK):
                        self._check_cancel()
                        hasher.write(chunk)
                        self._update(bytes_done=done_bytes + hasher.bytes_written)
            # Size check (actual bytes, not just the header)
            if hasher is None or hasher.bytes_written != pkg["size"]:
                got = hasher.bytes_written if hasher else 0
                raise ArabicInstallerError(
                    f"{pkg['name']}: downloaded {got} bytes, expected "
                    f"{pkg['size']}. Download failed or was truncated."
                )
            # Integrity check
            self._update(stage="verifying")
            self._check_cancel()
            digest = hasher.hexdigest()
            if digest != pkg["sha256"]:
                raise ArabicInstallerError(
                    f"{pkg['name']}: SHA256 mismatch (got {digest[:12]}..., "
                    f"expected {pkg['sha256'][:12]}...). Nothing was installed. "
                    "The download is corrupt, or the upstream file changed: "
                    "CAMeL Lab has re-uploaded release assets before without "
                    "changing the URL, which breaks the pinned checksum. Check "
                    "your connection and retry; if it fails again, report it so "
                    "the pinned digest can be updated in a new engine release."
                )
            log.info("arabic_installer_sha256_ok", package=pkg["name"], sha256=digest)
            # Extract to staging, then move into place
            self._update(stage="extracting")
            self._check_cancel()
            extract_dir = staging_root / f"{pkg['name']}.extract"
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            with zipfile.ZipFile(tmp_zip, "r") as zf:
                zf.extractall(extract_dir)
            dest = target / "data" / pkg["destination"]
            if dest.exists():
                shutil.rmtree(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            # os.replace works for dirs on POSIX; fall back to rename for
            # cross-device/temp setups.
            try:
                dest.rmdir()  # no-op when removed above; clears a leftover empty dir
            except OSError:
                pass
            extract_dir.rename(dest)
            return done_bytes + int(pkg["size"])
        finally:
            tmp_zip.unlink(missing_ok=True)
            # The extract dir was either renamed into place or the install
            # failed; nothing in staging is worth keeping either way.
            shutil.rmtree(staging_root, ignore_errors=True)

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise _JobCancelledError()

    def _cleanup_partial(self, target: Path, pending: list[dict[str, Any]]) -> None:
        """Best-effort removal of partial downloads/staging after error or
        cancel. Installed packages are left in place (they are complete and
        verified); the job status reports what finished."""
        try:
            staging = target / ".staging"
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        except OSError:
            pass


class _JobCancelledError(Exception):
    """Internal control-flow signal for cooperative cancellation."""


# --------------------------------------------------------------------------- #
# Process-wide singleton (one install job per engine process)
# --------------------------------------------------------------------------- #

_installer: ArabicDataInstaller | None = None
_installer_lock = threading.Lock()


def get_arabic_installer() -> ArabicDataInstaller:
    global _installer
    with _installer_lock:
        if _installer is None:
            _installer = ArabicDataInstaller()
        return _installer


def reset_installer_for_tests() -> None:
    global _installer
    with _installer_lock:
        _installer = None
