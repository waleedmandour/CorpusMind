"""Student Mode — the classroom "teacher-as-server" feature (v1.2.9).

Lets a teacher running the desktop app open a scoped classroom server:
students on their own phones/tablets open a URL/QR in their normal
browser and get a read + analysis + AI-chat view of the teacher's
corpora, without any write access to the teacher's data or settings.

ARCHITECTURE (one paragraph)
----------------------------
The engine stays bound to ``127.0.0.1`` exactly as today. A bundled
Caddy sidecar (same PyInstaller onedir as the engine) terminates the
classroom TLS/HTTP port, serves the bundled PWA, and reverse-proxies
``/api/*`` to the loopback engine, stamping every proxied request with
an ``X-CorpusMind-Classroom: 1`` header. The engine's auth middleware
treats proxy-stamped requests as untrusted: they must present either
the teacher token (full access) or the student token (allowlisted
read/analysis routes only). Direct loopback requests — the teacher's
own desktop app — remain trusted teacher access, so enabling Student
Mode changes NOTHING about the local experience. The proxy header is
the trust boundary: the engine port is unreachable from the LAN, and
only the locally-bundled Caddy injects the header.

Everything here is additive to the existing shared-lab mode
(``CORPUSMIND_AUTH_TOKEN``): when Student Mode is off, this module is
inert and the middleware behaves exactly as in v1.2.8.

Caddy lifecycle note: the plan-of-record proposed a Rust-side
supervisor, but engine-owned lifecycle was chosen deliberately — the
spawn/stop/Caddyfile logic is fully unit-testable in pytest, needs zero
Rust changes (the binary travels INSIDE the engine's PyInstaller
onedir, so the existing packaging mechanism is extended, not
duplicated), and the watchdog below (POSIX PDEATHSIG / Windows Job
Object) kills Caddy if the engine ever dies first.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

STUDENT_PROXY_HEADER = "X-CorpusMind-Classroom"
# v1.2.9 audit: the student PWA sends a random per-browser-session ID so the
# anonymous audit alias (S-1, S-2, …) stays stable across WiFi roaming and
# distinct even when many devices share one NAT address.
STUDENT_SESSION_HEADER = "X-CorpusMind-Session"
DEFAULT_HTTPS_PORT = 8483
DEFAULT_HTTP_PORT = 8484
DEFAULT_STUDENT_MODEL = "llama3.2:3b"
DEFAULT_NUM_PARALLEL = 4
MAX_STUDENTS = 20
# How long after their last request a student IP counts as "connected".
ACTIVE_WINDOW_S = 10 * 60
# The auto seat limit (device + LM sized) is re-probed at most this often —
# the probe may run nvidia-smi and ask Ollama for the model size, neither of
# which belongs on the per-request hot path.
SEATS_CACHE_TTL_S = 60.0
# A classroom-full rejection is logged once per student per this window so
# a tablet auto-retrying cannot flood the audit log.
FULL_DENY_LOG_WINDOW_S = 60.0

# Dev-checkout Caddy location (engine/caddy-bin/caddy). Module-level so
# tests can point it at a temp dir; the frozen app never uses it.
_DEV_CADDY_DIR = Path(__file__).resolve().parent.parent / "caddy-bin" / (
    "caddy.exe" if sys.platform.startswith("win") else "caddy"
)


# --------------------------------------------------------------------------- #
# Config persistence
# --------------------------------------------------------------------------- #

@dataclass
class ServerModeConfig:
    """Persisted classroom configuration (<data_dir>/server-mode/config.json).

    Tokens are generated once and persisted so student QR links survive
    engine restarts; the teacher can rotate them by disabling and
    re-enabling with rotate=True.
    """

    enabled: bool = False
    mode: str = "secure"  # "secure" (Caddy tls internal) | "simple" (plain HTTP)
    https_port: int = DEFAULT_HTTPS_PORT
    http_port: int = DEFAULT_HTTP_PORT
    student_model: str = DEFAULT_STUDENT_MODEL
    num_parallel: int = DEFAULT_NUM_PARALLEL
    teacher_token: str = ""
    student_token: str = ""
    enabled_at: str = ""
    # v1.2.9 audit + seat limit:
    # max_students None → auto: derived from the teacher's device memory +
    # the classroom model size (estimate_students), re-probed every
    # SEATS_CACHE_TTL_S; an explicit number overrides the estimate.
    max_students: int | None = None
    audit_enabled: bool = True

    def sanitize(self) -> None:
        if self.mode not in ("secure", "simple"):
            self.mode = "secure"
        self.https_port = max(1024, min(65535, int(self.https_port or DEFAULT_HTTPS_PORT)))
        self.http_port = max(1024, min(65535, int(self.http_port or DEFAULT_HTTP_PORT)))
        self.num_parallel = max(1, min(16, int(self.num_parallel or DEFAULT_NUM_PARALLEL)))
        self.student_model = (self.student_model or DEFAULT_STUDENT_MODEL).strip() or DEFAULT_STUDENT_MODEL
        if self.max_students is not None:
            try:
                self.max_students = max(1, min(99, int(self.max_students)))
            except (TypeError, ValueError):
                self.max_students = None
        self.audit_enabled = bool(self.audit_enabled)


def config_path(settings: Any) -> Path:
    return Path(settings.data_dir).expanduser() / "server-mode" / "config.json"


def load_config(settings: Any) -> ServerModeConfig:
    p = config_path(settings)
    if not p.is_file():
        return ServerModeConfig()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        cfg = ServerModeConfig(**{k: data[k] for k in ServerModeConfig.__dataclass_fields__ if k in data})
        cfg.sanitize()
        return cfg
    except Exception:
        return ServerModeConfig()


def save_config(settings: Any, cfg: ServerModeConfig) -> None:
    p = config_path(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
    try:
        # The file holds bearer tokens — keep it owner-only where POSIX
        # permissions apply (Windows ACLs handle this via the profile dir).
        os.chmod(p, 0o600)
    except OSError:
        pass


def ensure_tokens(cfg: ServerModeConfig, *, rotate: bool = False) -> None:
    if rotate or not cfg.teacher_token:
        cfg.teacher_token = "cm_teach_" + secrets.token_urlsafe(24)
    if rotate or not cfg.student_token:
        cfg.student_token = "cm_study_" + secrets.token_urlsafe(24)


# --------------------------------------------------------------------------- #
# Student route allowlist
# --------------------------------------------------------------------------- #

# (methods, compiled regex) — everything under /api/v1 NOT matched here is
# denied to the student role with 403. Grouped by capability. Read/analysis
# + AI chat only: no uploads, deletes, recompile, subcorpus management,
# settings, model management, export-queue admin, or server-mode itself.
_STUDENT_ROUTES: list[tuple[set[str], re.Pattern[str]]] = [
    # Health / version / framework registry (all read-only).
    ({"GET"}, re.compile(r"^/api/v1/health(/ready|/resources)?$")),
    ({"GET"}, re.compile(r"^/api/v1/version$")),
    ({"GET"}, re.compile(r"^/api/v1/frameworks$")),
    # Project / corpus / document listing (read-only).
    ({"GET"}, re.compile(r"^/api/v1/projects$")),
    ({"GET"}, re.compile(r"^/api/v1/projects/[^/]+$")),
    ({"GET"}, re.compile(r"^/api/v1/projects/[^/]+/corpora$")),
    ({"GET"}, re.compile(r"^/api/v1/corpora/[^/]+$")),
    ({"GET"}, re.compile(r"^/api/v1/corpora/[^/]+/documents$")),
    ({"GET"}, re.compile(r"^/api/v1/corpora/[^/]+/documents/stats$")),
    ({"GET"}, re.compile(r"^/api/v1/corpora/[^/]+/subcorpora$")),
    # Core analysis tools.
    ({"POST"}, re.compile(r"^/api/v1/corpora/[^/]+/concordance$")),
    ({"POST"}, re.compile(r"^/api/v1/corpora/[^/]+/concordance/vector$")),
    ({"POST"}, re.compile(r"^/api/v1/corpora/[^/]+/frequency$")),
    ({"POST"}, re.compile(r"^/api/v1/corpora/[^/]+/collocations$")),
    ({"POST"}, re.compile(r"^/api/v1/corpora/[^/]+/collocations/network$")),
    ({"POST"}, re.compile(r"^/api/v1/corpora/[^/]+/collocations/network/expand$")),
    ({"POST"}, re.compile(r"^/api/v1/corpora/[^/]+/keyness$")),
    ({"POST"}, re.compile(r"^/api/v1/corpora/[^/]+/dispersion$")),
    ({"POST"}, re.compile(r"^/api/v1/corpora/[^/]+/groups/frequency$")),
    ({"GET"}, re.compile(r"^/api/v1/corpora/[^/]+/readability$")),
    # Grammar / POS / semantics / discourse / sentiment / vocab (analysis).
    ({"POST"}, re.compile(r"^/api/v1/corpora/[^/]+/(ngrams|pos-analysis|semantic-analysis|grammar|dependencies|ud-profile|valency|sentence-tree|dep-concordance|discourse|vocab-profile|sentiment|metaphor-candidates)$")),
    ({"GET"}, re.compile(r"^/api/v1/corpora/[^/]+/grammar/patterns$")),
    ({"GET"}, re.compile(r"^/api/v1/corpora/[^/]+/sentences$")),
    ({"GET"}, re.compile(r"^/api/v1/corpora/[^/]+/discourse/taxonomies$")),
    ({"GET"}, re.compile(r"^/api/v1/discourse/persuasion/health$")),
    # Direct analysis-result downloads (files returned inline; NOT the
    # server-side export queue, which stays teacher-only).
    ({"POST"}, re.compile(r"^/api/v1/corpora/[^/]+/export/(concordance|frequency|collocations|keyness)(\.xlsx)?$")),
    ({"POST"}, re.compile(r"^/api/v1/corpora/[^/]+/export/collocations\.network\.(svg|png)$")),
    ({"GET"}, re.compile(r"^/api/v1/corpora/[^/]+/methods.pdf$")),
    # Learner Research (analysis).
    ({"POST"}, re.compile(r"^/api/v1/corpora/[^/]+/learner/(caf|errors|cia)$")),
    ({"POST"}, re.compile(r"^/api/v1/learner/caf-text$")),
    # Arabic / bilingual tools (analysis).
    ({"POST"}, re.compile(r"^/api/v1/arabic/(analyze|roots|clitics|buckwalter|dediacritize|normalize|dialect|register)$")),
    ({"GET"}, re.compile(r"^/api/v1/arabic/backends$")),
    ({"POST"}, re.compile(r"^/api/v1/bilingual/(align|parallel-concordance|translate)$")),
    # AI Assistant: chat + tool registry + suggestions. Conversation
    # history is deliberately NOT student-visible (the teacher's own
    # chats live in the same store; students chat fresh each session).
    ({"POST"}, re.compile(r"^/api/v1/ai/chat$")),
    ({"GET"}, re.compile(r"^/api/v1/ai/tools$")),
    ({"GET"}, re.compile(r"^/api/v1/ai/query-suggestions$")),
    ({"POST"}, re.compile(r"^/api/v1/ai/query-suggestions/dynamic$")),
    # Read-only reference-corpus registry + research-integrity reads.
    ({"GET"}, re.compile(r"^/api/v1/reference-corpora$")),
    ({"GET"}, re.compile(r"^/api/v1/reference-corpora/[^/]+/status$")),
    ({"GET"}, re.compile(r"^/api/v1/research/precheck/[^/]+$")),
    ({"GET"}, re.compile(r"^/api/v1/research/bundled-references$")),
    ({"GET"}, re.compile(r"^/api/v1/research/bundled-references/[^/]+$")),
    ({"GET"}, re.compile(r"^/api/v1/stopword-lists$")),
    # Read-only hub catalogue (search/metadata only — downloads stay teacher-only).
    ({"GET"}, re.compile(r"^/api/v1/hub/(search|catalogue)$")),
]


def student_route_allowed(method: str, path: str) -> bool:
    """True when the student role may call this (method, path)."""
    for methods, pattern in _STUDENT_ROUTES:
        if method in methods and pattern.match(path):
            return True
    return False


def student_allowed_summary() -> list[dict[str, str]]:
    """Human-readable allowlist for docs/UI (one row per rule)."""
    return [{"methods": ",".join(sorted(m)), "path": p.pattern} for m, p in _STUDENT_ROUTES]


# --------------------------------------------------------------------------- #
# Caddy sidecar
# --------------------------------------------------------------------------- #

def find_caddy_binary(settings: Any) -> Path | None:
    """Locate the bundled Caddy binary.

    Search order:
      1. CORPUSMIND_CADDY_BIN env;
      2. next to the frozen engine executable (caddy/caddy[.exe]);
      3. the PyInstaller _internal dir (caddy/ collected into _internal);
      4. dev checkout: engine/caddy-bin/caddy[.exe];
      5. PATH.
    """
    exe = "caddy.exe" if sys.platform.startswith("win") else "caddy"
    env = (os.environ.get("CORPUSMIND_CADDY_BIN", "") or "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_file():
            return p
    here = Path(sys.executable).resolve().parent
    for candidate in (
        here / "caddy" / exe,
        here / exe,
        here / "_internal" / "caddy" / exe,
    ):
        if candidate.is_file():
            return candidate
    if _DEV_CADDY_DIR.is_file():
        return _DEV_CADDY_DIR
    which = shutil.which("caddy")
    return Path(which) if which else None


def find_web_dist(settings: Any) -> Path | None:
    """The PWA build Caddy serves to student browsers.

    The PyInstaller spec collects the repo's web/dist as ``web-dist`` when
    present; dev checkouts fall back to the repo's web/dist.
    """
    exe_name = "index.html"
    meipass = getattr(sys, "_MEIPASS", None)
    candidates = []
    if meipass:
        candidates.append(Path(meipass) / "web-dist")
    here = Path(__file__).resolve().parent          # engine/app
    candidates.append(here.parent / "web-dist")      # engine/_internal? frozen alt
    candidates.append(here.parent.parent / "web" / "dist")  # dev checkout
    for c in candidates:
        if (c / exe_name).is_file():
            return c
    return None


def server_mode_dir(settings: Any) -> Path:
    return Path(settings.data_dir).expanduser() / "server-mode"


def ensure_classroom_certificates(settings: Any, cfg: ServerModeConfig) -> tuple[Path, Path, Path]:
    """Generate (idempotently, per enable) the classroom local CA + server
    certificate with the engine's own `cryptography` dependency.

    WHY NOT CADDY'S `tls internal`: Caddy's internal CA tries to install its
    root into the OS trust store at startup (via sudo on Linux / native
    trust APIs elsewhere). On machines without passwordless sudo that step
    fails and — with Caddy 2.10 — TLS handshakes fail with an internal
    error before the classroom is even reachable. Issuing the CA ourselves
    is dependency-free (cryptography ships with the engine), needs no
    privileges, works identically on every platform, and gives us the exact
    root file students install for the one-time trust step.

    Returns (server_cert, server_key, ca_cert) paths. The leaf covers
    localhost/127.0.0.1, the hostname, and every detected LAN IP so the
    QR URL validates against it.
    """
    import datetime
    import ipaddress
    import socket as _socket

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    certs_dir = server_mode_dir(settings) / "certs"
    certs_dir.mkdir(parents=True, exist_ok=True)
    ca_key_p = certs_dir / "classroom-ca.key"
    ca_crt_p = certs_dir / "classroom-ca.crt"      # the file students trust
    srv_key_p = certs_dir / "classroom-server.key"
    srv_crt_p = certs_dir / "classroom-server.crt"

    now = datetime.datetime.now(datetime.UTC)

    def _name(cn: str) -> x509.Name:
        return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])

    # --- CA (persisted: regenerate only when missing or stale) ---
    if ca_crt_p.is_file() and ca_key_p.is_file():
        try:
            ca_cert = x509.load_pem_x509_certificate(ca_crt_p.read_bytes())
            if (ca_cert.not_valid_after_utc - now).days > 30:
                ca_key = serialization.load_pem_private_key(ca_key_p.read_bytes(), password=None)
            else:
                raise ValueError("CA expiring soon")
        except Exception:
            ca_key = None
    else:
        ca_key = None
    if ca_key is None:
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(_name("CorpusMind Classroom CA"))
            .issuer_name(_name("CorpusMind Classroom CA"))
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(ca_key, hashes.SHA256())
        )
        ca_key_p.write_bytes(ca_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        ca_crt_p.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))

    # --- Leaf (regenerated on every enable: LAN IPs may have changed) ---
    sans: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    try:
        host = _socket.gethostname()
        if host:
            sans.append(x509.DNSName(host))
    except Exception:
        pass
    for ip in lan_ips():
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            continue

    srv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    srv_cert = (
        x509.CertificateBuilder()
        .subject_name(_name("CorpusMind Classroom"))
        .issuer_name(ca_cert.subject)
        .public_key(srv_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=825))  # iOS 825-day limit
        .add_extension(
            x509.SubjectAlternativeName(sans), critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    srv_key_p.write_bytes(srv_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    srv_crt_p.write_bytes(srv_cert.public_bytes(serialization.Encoding.PEM))

    try:
        os.chmod(ca_key_p, 0o600)
        os.chmod(srv_key_p, 0o600)
    except OSError:
        pass
    return srv_crt_p, srv_key_p, ca_crt_p


def _caddy_path(p: Path) -> str:
    """Render a filesystem path as a safe Caddyfile token.

    v1.2.10 release blocker: Windows home directories contain spaces
    (``C:\\Users\\Waleed Mandour\\.corpusmind\\...``), and an unquoted
    path with a space lexes as TWO tokens — Caddy fails to parse the
    Caddyfile and exits code 1 at startup (invisible on dev machines
    whose paths have no spaces). Double-quoted strings do NOT fix it on
    Windows either: the Caddyfile lexer processes backslash escapes
    inside double quotes, so ``C:\\Users`` is an unrecognized ``\\U``
    escape. Backtick strings are raw literals, and Go's filesystem layer
    accepts forward slashes on Windows — so the safe form is a
    backtick-quoted, forward-slashed path.
    """
    return "`" + Path(p).as_posix() + "`"


def generate_caddyfile(
    settings: Any,
    cfg: ServerModeConfig,
    web_dist: Path,
    ca_share_dir: Path,
    *,
    server_cert: Path | None = None,
    server_key: Path | None = None,
) -> str:
    """Render the Caddyfile for the configured classroom mode.

    - secure: HTTPS on https_port with the engine-issued local certificate
      (see ensure_classroom_certificates) + a plain-HTTP helper port that
      serves the CA root for the one-time student trust step.
    - simple: plain HTTP only, for closed/trusted classroom networks.
    Both modes proxy /api/* to the loopback engine with the classroom
    header stamped, and serve the PWA from disk with SPA fallback.
    """
    engine = f"127.0.0.1:{settings.port}"
    log_path = server_mode_dir(settings) / "caddy.log"
    lines = [
        "{",
        "\tadmin off",
        # Explicit https://<port> sites otherwise make Caddy bind :80 for the
        # HTTP->HTTPS redirect — requires privileges we must not assume.
        "\tauto_https disable_redirects",
        "\tlog {",
        f"\t\toutput file {_caddy_path(log_path)}",
        "\t\tlevel WARN",
        "\t}",
        "}",
        "",
    ]

    def proxy_block(indent: str) -> list[str]:
        return [
            f"{indent}handle /api/* {{",
            f"{indent}\treverse_proxy {engine} {{",
            f'{indent}\t\theader_up {STUDENT_PROXY_HEADER} "1"',
            f"{indent}\t}}",
            f"{indent}}}",
        ]

    if cfg.mode == "secure":
        if server_cert is None or server_key is None:
            raise RuntimeError("secure mode requires the classroom server certificate")
        lines += [
            f"https://:{cfg.https_port} {{",
            f"\ttls {_caddy_path(server_cert)} {_caddy_path(server_key)}",
            "\tencode zstd gzip",
            *proxy_block("\t"),
            "\thandle {",
            f"\t\troot * {_caddy_path(web_dist)}",
            "\t\ttry_files {path} /index.html",
            "\t\tfile_server",
            "\t}",
            "}",
            "",
            "# One-time certificate trust helper (classroom LAN only): serves",
            "# the classroom local root CA so each student device can trust it.",
            f"http://:{cfg.http_port} {{",
            f"\troot * {_caddy_path(ca_share_dir)}",
            "\tfile_server",
            "}",
        ]
    else:
        lines += [
            f"http://:{cfg.http_port} {{",
            "\tencode zstd gzip",
            *proxy_block("\t"),
            "\thandle {",
            f"\t\troot * {_caddy_path(web_dist)}",
            "\t\ttry_files {path} /index.html",
            "\t\tfile_server",
            "\t}",
            "}",
        ]
    return "\n".join(lines) + "\n"


def _caddy_data_dir(settings: Any) -> Path:
    return server_mode_dir(settings) / "caddy-data"


def _posix_close_on_parent_death() -> None:  # pragma: no cover — POSIX only
    """preexec_fn: ask the kernel to SIGTERM Caddy if the engine dies."""
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(1, 15)  # PR_SET_PDEATHSIG, SIGTERM
    except Exception:
        pass


def _windows_kill_on_engine_exit(proc: subprocess.Popen) -> None:  # pragma: no cover — Windows only
    """Put Caddy in a Job Object that dies with this process (engine)."""
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

        class JobObjectBasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_void_p),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class JobObjectExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JobObjectBasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        job = kernel32.CreateJobObjectW(None, None)
        info = JobObjectExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel32.SetInformationJobObject(
            job, 9, ctypes.byref(info), ctypes.sizeof(info)
        )
        kernel32.AssignProcessToJobObject(job, int(proc.handle))
        # Intentionally keep `job` alive for the engine's lifetime: closing
        # it would kill Caddy. Leaked on purpose — the OS cleans up at exit.
    except Exception:
        pass


def stop_caddy(state: ServerModeState) -> None:
    proc = state.caddy_proc
    state.caddy_proc = None
    if proc is None:
        return
    if proc.poll() is None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        except Exception:
            pass


def _caddy_log_tail(sm_dir: Path, limit: int = 400) -> str:
    """Last ``limit`` chars of caddy-stdout.log, for teacher-facing errors.

    The file is opened in append-binary mode by the Popen redirect; reading
    it through a separate handle is safe (append-only writer). Any read
    failure degrades to an empty string — the error still names the log.
    """
    try:
        with open(sm_dir / "caddy-stdout.log", encoding="utf-8", errors="replace") as f:
            return f.read()[-limit:].strip()
    except OSError:
        return ""


def spawn_caddy(settings: Any, state: ServerModeState) -> dict[str, Any]:
    """Write the Caddyfile, launch Caddy, wait for readiness, stage the CA.

    Idempotent: an already-running supervised Caddy is reused. Raises
    RuntimeError with a teacher-readable message on any failure.
    """
    cfg = state.config
    if state.caddy_proc and state.caddy_proc.poll() is None:
        return {"reused": True}

    caddy_bin = find_caddy_binary(settings)
    if caddy_bin is None:
        raise RuntimeError(
            "The Caddy sidecar binary was not found next to the engine. "
            "Reinstall CorpusMind (or run scripts/fetch_caddy.py in a dev "
            "checkout) and try again."
        )
    web_dist = find_web_dist(settings)
    if web_dist is None:
        raise RuntimeError(
            "The bundled web app (web-dist) was not found in this engine "
            "build — Student Mode needs it to serve student browsers."
        )

    sm_dir = server_mode_dir(settings)
    sm_dir.mkdir(parents=True, exist_ok=True)
    ca_share = sm_dir / "ca-share"
    ca_share.mkdir(parents=True, exist_ok=True)

    server_cert = server_key = None
    if cfg.mode == "secure":
        server_cert, server_key, ca_crt = ensure_classroom_certificates(settings, cfg)
        # Stage the CA where the HTTP helper port serves it to students.
        try:
            shutil.copyfile(ca_crt, ca_share / "root.crt")
        except OSError:
            pass

    caddyfile = sm_dir / "Caddyfile"
    caddyfile.write_text(
        generate_caddyfile(settings, cfg, web_dist, ca_share,
                           server_cert=server_cert, server_key=server_key),
        encoding="utf-8",
    )

    # Orphan sweep: a Caddy left running from a crashed engine still holds
    # the port. It wrote its pidfile; kill it before starting fresh.
    pidfile = sm_dir / "caddy.pid"
    if pidfile.is_file():
        try:
            old = int(pidfile.read_text().strip() or 0)
            if old > 0 and old != os.getpid():
                if sys.platform.startswith("win"):
                    subprocess.run(["taskkill", "/PID", str(old), "/T", "/F"],
                                   capture_output=True, timeout=10)
                else:
                    os.kill(old, 15)
        except (ValueError, ProcessLookupError, PermissionError, subprocess.TimeoutExpired, OSError):
            pass

    caddy_data = _caddy_data_dir(settings)
    caddy_config = sm_dir / "caddy-config"
    caddy_data.mkdir(parents=True, exist_ok=True)
    caddy_config.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["XDG_DATA_HOME"] = str(caddy_data)
    env["XDG_CONFIG_HOME"] = str(caddy_config)

    kwargs: dict[str, Any] = {"env": env, "cwd": str(sm_dir)}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["preexec_fn"] = _posix_close_on_parent_death  # type: ignore[assignment]

    log_file = open(sm_dir / "caddy-stdout.log", "ab")
    proc = subprocess.Popen(
        [str(caddy_bin), "run", "--config", str(caddyfile), "--adapter", "caddyfile"],
        stdout=log_file, stderr=subprocess.STDOUT, **kwargs,
    )
    state.caddy_proc = proc
    state.caddy_log_file = log_file
    state.caddy_started_at = time.time()
    try:
        pidfile.write_text(str(proc.pid))
    except OSError:
        pass
    if sys.platform.startswith("win"):
        _windows_kill_on_engine_exit(proc)  # pragma: no cover — Windows only

    # Wait for readiness: Caddy must serve the bundled PWA. We deliberately
    # probe the STATIC file (no engine round-trip): probing /api/v1/health
    # would deadlock a single-worker engine — the proxy forwards that request
    # back to the very event loop this synchronous probe is blocking.
    import httpx

    verify = False  # the classroom CA is not in the OS trust store (yet)
    deadline = time.time() + 20
    last_err = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            state.caddy_proc = None
            # Surface WHY Caddy died (config parse errors are the classic
            # case — the teacher should not have to open the log to learn).
            tail = _caddy_log_tail(sm_dir)
            detail = f" Log tail: {tail}" if tail else ""
            raise RuntimeError(
                f"Caddy exited immediately (code {proc.returncode}). "
                f"Check {sm_dir / 'caddy-stdout.log'}.{detail}"
            )
        scheme = "https" if cfg.mode == "secure" else "http"
        port = cfg.https_port if cfg.mode == "secure" else cfg.http_port
        try:
            r = httpx.get(f"{scheme}://127.0.0.1:{port}/index.html",
                          timeout=2.0, verify=verify)
            if r.status_code == 200:
                break
            last_err = f"status {r.status_code}"
        except Exception as exc:
            last_err = str(exc)
        time.sleep(0.5)
    else:
        stop_caddy(state)
        raise RuntimeError(
            f"Caddy did not become ready on port {port} ({last_err or 'timeout'})."
        )

    # Secure mode: the CA is engine-issued (ensure_classroom_certificates)
    # and already staged into ca-share by the caller — nothing to wait for.
    ca_staged = (cfg.mode != "secure") or (ca_share / "root.crt").is_file()
    return {"reused": False, "pid": proc.pid, "ca_staged": ca_staged}


def caddy_version(caddy_bin: Path | None) -> str | None:
    if caddy_bin is None or not caddy_bin.is_file():
        return None
    try:
        out = subprocess.run([str(caddy_bin), "version"], capture_output=True,
                             text=True, timeout=10)
        return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Runtime state + networking helpers
# --------------------------------------------------------------------------- #

@dataclass
class ServerModeState:
    """In-memory classroom state attached to ``app.state.server_mode``."""

    config: ServerModeConfig = field(default_factory=ServerModeConfig)
    caddy_proc: subprocess.Popen | None = None
    caddy_log_file: Any = None
    caddy_started_at: float = 0.0
    caddy_error: str = ""
    # v1.2.10 release fix: the Ollama LAN-exposure probe is cached for 60 s.
    # The teacher card polls status every 5 s while the classroom runs; a
    # fresh TCP probe per poll (0.3 s timeout × N interfaces) both stalls
    # the poll and makes the warning flicker when a connect is borderline.
    exposure_cache: tuple[float, dict[str, Any]] | None = None
    # student IP → last-seen monotonic timestamp (lightweight counter, no
    # session store — the plan explicitly asks for the cheap version).
    student_seen: dict[str, float] = field(default_factory=dict)
    # v1.2.9 audit + anonymous aliases + seat limit. The alias map and the
    # salted-hash salt both live ONLY here (process memory): the audit file
    # never sees IPs, session IDs or tokens, so it cannot be de-anonymised
    # after the fact. Counters restart with each classroom enable.
    audit: Any = None  # app.classroom_audit.ClassroomAudit (lazy)
    aliases: dict[str, str] = field(default_factory=dict)
    # alias → last-seen monotonic timestamp. Primary seat counter: aliases
    # are per-device (session header), so two students behind one NAT
    # address count as two seats, unlike the IP-based fallback below.
    alias_seen: dict[str, float] = field(default_factory=dict)
    _alias_counter: int = 0
    joined_total: int = 0
    chats_total: int = 0
    _cap_cache: tuple[float, int, str] | None = None
    _full_deny_logged: dict[str, float] = field(default_factory=dict)

    def note_student(self, ip: str) -> None:
        if not ip:
            return
        now = time.monotonic()
        # Prune opportunistically — the dict is bounded by classroom size.
        if len(self.student_seen) > 64:
            self.student_seen = {k: v for k, v in self.student_seen.items()
                                 if now - v <= ACTIVE_WINDOW_S}
        self.student_seen[ip] = now

    def active_students(self) -> int:
        now = time.monotonic()
        fresh_alias = sum(1 for ts in self.alias_seen.values()
                          if now - ts <= ACTIVE_WINDOW_S)
        fresh_ip = sum(1 for ts in self.student_seen.values()
                       if now - ts <= ACTIVE_WINDOW_S)
        # Aliases are the finer-grained (per-device) count; the IP count
        # covers header-less clients that never got an alias.
        return max(fresh_alias, fresh_ip)

    def touch_alias(self, alias: str) -> None:
        now = time.monotonic()
        if len(self.alias_seen) > 128:
            self.alias_seen = {a: ts for a, ts in self.alias_seen.items()
                               if now - ts <= ACTIVE_WINDOW_S}
        self.alias_seen[alias] = now

    # ------------------------------------------------------------------ #
    # Anonymous aliases + audit (v1.2.9)
    # ------------------------------------------------------------------ #

    def ensure_audit(self, settings: Any) -> Any:
        """Lazily create the audit writer honouring config.audit_enabled."""
        from app.classroom_audit import ClassroomAudit, audit_dir

        if self.audit is None:
            self.audit = ClassroomAudit(audit_dir(settings), enabled=self.config.audit_enabled)
        else:
            self.audit.enabled = self.config.audit_enabled
        return self.audit

    def reset_classroom_session(self) -> None:
        """Fresh numbering/counters per enable — aliases never survive a
        restart, which is exactly what keeps the log anonymous."""
        self.aliases.clear()
        self._alias_counter = 0
        self.alias_seen.clear()
        self.joined_total = 0
        self.chats_total = 0
        self._cap_cache = None
        self._full_deny_logged.clear()

    def client_key(self, request: Any) -> str:
        """Alias key for a proxied request (see ClassroomAudit.alias_key)."""
        header = request.headers.get(STUDENT_SESSION_HEADER, "").strip()
        client_ip = request.client.host if request.client else ""
        audit = self.audit
        if audit is None:
            # Audit disabled — still need a stable key for join counting.
            return f"sid:{header}" if header else f"ip:{client_ip}"
        return audit.alias_key(header, client_ip)

    def alias_for(self, request: Any) -> str:
        """Return (assigning on first sight) the anonymous alias for this
        request, writing a ``student_join`` audit event for newcomers."""
        key = self.client_key(request)
        alias = self.aliases.get(key)
        if alias is None:
            self._alias_counter += 1
            alias = f"S-{self._alias_counter}"
            self.aliases[key] = alias
            self.joined_total += 1
            if self.audit is not None:
                self.audit.write(
                    "student_join",
                    alias=alias,
                    students_active=self.active_students(),
                    students_joined_total=self.joined_total,
                )
        return alias

    def log_request(self, request: Any, role: str, status: int, dur_ms: int) -> None:
        """One audit line per classroom API call (aliases only, never IPs)."""
        if self.audit is None:
            return
        alias = "teacher" if role == "teacher" else self.aliases.get(self.client_key(request), "S-?")
        self.audit.write(
            "api_request",
            alias=alias,
            role=role,
            method=request.method,
            path=request.url.path,
            status=status,
            dur_ms=dur_ms,
        )

    def log_denied(self, request: Any, role: str, status: int, reason: str) -> None:
        if self.audit is None:
            return
        alias = self.aliases.get(self.client_key(request))
        self.audit.write(
            "denied",
            alias=alias,
            role=role,
            method=request.method,
            path=request.url.path,
            status=status,
            reason=reason,
        )

    def log_chat(
        self,
        request: Any,
        *,
        question: str,
        response: str = "",
        model: str = "",
        elapsed_ms: int = 0,
        grounded: bool | None = None,
        turn_id: int | None = None,
        error: str = "",
    ) -> None:
        """The heart of the audit contract: what students asked the local LM
        and exactly what it answered (both truncated only at a very
        generous cap — see classroom_audit.AUDIT_TEXT_MAX)."""
        alias = self.aliases.get(self.client_key(request), "S-?")
        if self.audit is not None:
            self.audit.write(
                "chat_error" if error else "chat",
                alias=alias,
                question=question,
                response=response or None,
                model=model,
                elapsed_ms=elapsed_ms,
                grounded=grounded,
                turn_id=turn_id,
                error=error or None,
            )
        if error:
            return
        self.chats_total += 1

    def log_full_deny(self, request: Any, seats: int) -> bool:
        """Log a classroom-full rejection at most once per student per window.
        Returns True when a line was actually written."""
        key = self.client_key(request)
        now = time.monotonic()
        last = self._full_deny_logged.get(key, 0.0)
        if now - last < FULL_DENY_LOG_WINDOW_S:
            return False
        self._full_deny_logged[key] = now
        if self.audit is not None:
            self.audit.write(
                "denied",
                alias=self.aliases.get(key),
                role="student",
                method=request.method,
                path=request.url.path,
                status=429,
                reason=f"classroom_full ({seats} seats)",
            )
        return True

    # ------------------------------------------------------------------ #
    # Seat limit (device + LM sized)
    # ------------------------------------------------------------------ #

    async def effective_seats(self, settings: Any) -> tuple[int, str]:
        """(max concurrent students, source) — manual override wins, else
        the auto estimate from the shared RAM/VRAM probe, else the hard
        MAX_STUDENTS fallback. Cached SEATS_CACHE_TTL_S: the probe may run
        nvidia-smi and ask Ollama, so it must not run per request."""
        if self.config.max_students:
            return self.config.max_students, "manual"
        now = time.monotonic()
        if self._cap_cache and now - self._cap_cache[0] < SEATS_CACHE_TTL_S:
            return self._cap_cache[1], self._cap_cache[2]
        size = 0
        try:
            size, _ = await ollama_model_size(
                settings.ollama_base_url, self.config.student_model
            )
        except Exception:
            size = 0
        try:
            import anyio

            est = await anyio.to_thread.run_sync(
                lambda: estimate_students(size, self.config.num_parallel)
            )
        except Exception:
            est = {"students_max": None}
        if est.get("students_max"):
            seats, source = int(est["students_max"]), "auto"
        else:
            # Cannot measure (no Ollama / no memory probe): still enforce a
            # conservative ceiling so the classroom can never run away.
            seats, source = MAX_STUDENTS, "auto-fallback"
        self._cap_cache = (now, seats, source)
        return seats, source


async def ollama_model_size(base_url: str, wanted: str) -> tuple[int, str | None]:
    """On-disk size (bytes) of ``wanted`` from Ollama /api/tags, plus the
    resolved full name. 0/None when Ollama is unreachable."""
    import httpx

    from ai.providers import model_name_matches

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{base_url.rstrip('/')}/api/tags")
            if r.status_code == 200:
                for m in r.json().get("models", []):
                    name = m.get("name", "")
                    if model_name_matches(name, wanted):
                        return int(m.get("size", 0)), name
    except Exception:
        pass
    return 0, None


def lan_ips() -> list[str]:
    """Best-effort enumeration of this machine's LAN IPv4 addresses.

    Primary: the UDP-connect trick (no packets sent — connect() on a
    SOCK_DGRAM socket just picks a route). Secondary: resolving the local
    hostname. Loopback and link-local entries are dropped. Private-range
    addresses (RFC1918) are preferred; on hosts with only public-range
    interfaces (some containers/VPNs) those are reported rather than
    returning nothing — the UI shows the list so the teacher can pick.
    """
    import ipaddress

    candidates: list[str] = []

    def _add(ip: str) -> None:
        if not ip or ip in candidates:
            return
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return
        if not isinstance(addr, ipaddress.IPv4Address):
            return
        if addr.is_loopback or addr.is_link_local or addr.is_multicast:
            return
        candidates.append(ip)

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            _add(s.getsockname()[0])
        finally:
            s.close()
    except Exception:
        pass
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            _add(info[4][0])
    except Exception:
        pass

    private = [ip for ip in candidates
               if ipaddress.ip_address(ip).is_private]
    return private if private else candidates


def classroom_urls(settings: Any, cfg: ServerModeConfig, ip: str | None = None) -> dict[str, str]:
    """The URLs a QR code points students at, for the primary LAN IP."""
    ips = [ip] if ip else lan_ips()
    primary = ips[0] if ips else "localhost"
    base = (f"https://{primary}:{cfg.https_port}" if cfg.mode == "secure"
            else f"http://{primary}:{cfg.http_port}")
    urls = {"app": base, "server": base}
    if cfg.mode == "secure":
        urls["root_ca"] = f"http://{primary}:{cfg.http_port}/root.crt"
    return urls


# --------------------------------------------------------------------------- #
# Capacity estimation (reuses ai.hf_catalog's RAM/VRAM probe — no second probe)
# --------------------------------------------------------------------------- #

def estimate_students(model_size_bytes: int, num_parallel: int) -> dict[str, Any]:
    """Honest rule-of-thumb: how many concurrent students fit.

    Reuses the machine probe behind the HF GGUF explorer (ai.hf_catalog.
    machine_profile — /proc/meminfo, sysctl, or GlobalMemoryStatusEx plus
    nvidia-smi when present). Per-connection cost ≈ model weights ×1.15
    (runtime overhead) + a flat KV-cache/scratch allowance per parallel
    slot; we budget 85% of available memory and cap at MAX_STUDENTS.
    """
    from ai.hf_catalog import machine_profile

    profile = machine_profile()
    if model_size_bytes <= 0:
        return {
            "students_max": None,
            "note": "Model size unavailable (is Ollama running with the model pulled?)",
            "machine": _machine_dict(profile),
        }
    if profile.vram_total and profile.vram_available:
        budget = profile.vram_available
        source = "VRAM (nvidia-smi)"
    elif profile.ram_available:
        budget = profile.ram_available
        source = "available RAM"
    else:
        return {
            "students_max": None,
            "note": "Machine memory could not be detected.",
            "machine": _machine_dict(profile),
        }
    per_conn = model_size_bytes * 1.15 + 350 * 1024 ** 2 * max(1, num_parallel // 2)
    n = int((budget * 0.85) // per_conn)
    n = max(1, min(MAX_STUDENTS, n))
    return {
        "students_max": n,
        "note": (
            f"Estimate from {source} (model + {num_parallel} parallel slot(s)); "
            "rule-of-thumb only, not a guarantee."
        ),
        "machine": _machine_dict(profile),
    }


def _machine_dict(profile: Any) -> dict[str, Any]:
    return {
        "ram_total": profile.ram_total,
        "ram_available": profile.ram_available,
        "vram_total": profile.vram_total,
        "vram_available": profile.vram_available,
        "gpu_name": profile.gpu_name,
        "source": profile.source,
    }
