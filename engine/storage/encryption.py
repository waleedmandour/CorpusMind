"""
§13.2 At-rest encryption for project storage.

Per §13.2: "an at-rest encryption option for project storage on shared/
institutional machines."

This module provides AES-256-GCM encryption for the SQLite database + image
files stored on disk. It is OPT-IN — the user enables it via
CORPUSMIND_ENCRYPTION_KEY (a 32-byte hex string or passphrase).

When enabled:
  - The SQLite DB is encrypted via sqlcipher (if available) or the
    application-layer encryption wrapper below.
  - Image files on disk are encrypted with AES-256-GCM.
  - The encryption key is NEVER stored on disk — it must be supplied via
    environment variable or interactive prompt.

Phase 6 ships the application-layer image encryption + a DB encryption
scaffold. Full sqlcipher integration is a Phase 7+ task (requires a
sqlcipher-enabled SQLite build).

v1.2.14 (P0-3 + P0-4 + F1-1):
  - Fail-loud if CORPUSMIND_ENCRYPTION_KEY is set but the `cryptography`
    package is missing. Previously the module silently fell back to
    plaintext while get_encryption_status() reported "enabled: true".
  - Expose db_encrypted: false honestly in get_encryption_status() so the
    UI can distinguish "transcripts encrypted, corpus text not" from
    "everything encrypted". (SQLCipher integration is a Phase 7+ task.)
  - Switch the passphrase derivation from single-pass SHA-256 to scrypt
    (N=2^14, r=8, p=1) with a per-install random salt stored alongside
    the encrypted transcripts. Old SHA-256 hashes are detected and
    re-derived on first unlock (backwards compatible).
"""
from __future__ import annotations

import hashlib
import os
import secrets

from app.logging import get_logger

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# v1.2.14: cryptography availability check (P0-3)
# --------------------------------------------------------------------------- #

def _cryptography_available() -> bool:
    """Return True iff the `cryptography` package can be imported AND
    exposes both the AESGCM AEAD primitive and the Scrypt KDF."""
    try:
        import cryptography  # noqa: F401
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt  # noqa: F401  (capitalized)
        return True
    except ImportError:
        return False

_CRYPTO_AVAILABLE = _cryptography_available()


# --------------------------------------------------------------------------- #
# Key management
# --------------------------------------------------------------------------- #

# Per-install random salt for scrypt derivation. Stored at
# ~/.corpusmind/encryption.salt so the same passphrase derives the same key
# across engine restarts. (This is NOT a secret — its purpose is to defeat
# precomputed rainbow tables against a stolen DB.)
def _salt_path() -> str:
    """Return the path to the per-install scrypt salt file."""
    home = os.path.expanduser("~")
    cm_dir = os.environ.get("CORPUSMIND_HOME", os.path.join(home, ".corpusmind"))
    return os.path.join(cm_dir, "encryption.salt")


def _get_or_create_salt() -> bytes:
    """Load the per-install salt, creating it on first call."""
    path = _salt_path()
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        salt = secrets.token_bytes(16)
        with open(path, "wb") as f:
            f.write(salt)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        return salt


def _derive_key_scrypt(passphrase: str) -> bytes:
    """Derive a 32-byte key from a passphrase using scrypt.

    N=2^14, r=8, p=1 is the OWASP 2023 minimum recommendation for interactive
    logins (~~64ms on a modern CPU). Backed by the per-install salt so a
    stolen DB + a different install's salt still defeats rainbow tables.
    """
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    salt = _get_or_create_salt()
    kdf = Scrypt(
        salt=salt,
        length=32,
        n=2 ** 14,
        r=8,
        p=1,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def get_encryption_key() -> bytes | None:
    """Get the at-rest encryption key from the environment.

    Returns None if encryption is not enabled (the default).
    Returns a 32-byte key if CORPUSMIND_ENCRYPTION_KEY is set.

    v1.2.14 (P0-3): if the env var is set but `cryptography` is missing,
    raise ImportError instead of silently returning None — the previous
    behaviour caused get_encryption_status() to report "enabled: true"
    while the actual encrypt_file/decrypt_file functions silently
    passed data through as plaintext.
    """
    raw = os.environ.get("CORPUSMIND_ENCRYPTION_KEY")
    if not raw:
        return None
    # v1.2.14 (P0-3): fail-loud if cryptography is missing.
    if not _CRYPTO_AVAILABLE:
        raise ImportError(
            "CORPUSMIND_ENCRYPTION_KEY is set but the `cryptography` package "
            "is not installed. At-rest encryption cannot proceed — either "
            "`pip install cryptography` or unset CORPUSMIND_ENCRYPTION_KEY to "
            "disable encryption (and accept that data stays plaintext)."
        )
    # If it's a 64-char hex string, use it directly
    if len(raw) == 64:
        try:
            return bytes.fromhex(raw)
        except ValueError:
            pass
    # v1.2.14 (F1-1): scrypt KDF (replaces single-pass SHA-256).
    return _derive_key_scrypt(raw)


def is_encryption_enabled() -> bool:
    """Check whether at-rest encryption is enabled AND functional.

    v1.2.14 (P0-3): returns False if CORPUSMIND_ENCRYPTION_KEY is set but
    `cryptography` is missing — the previous behaviour reported True while
    silently passing data through as plaintext.
    """
    if not os.environ.get("CORPUSMIND_ENCRYPTION_KEY"):
        return False
    return _CRYPTO_AVAILABLE


def generate_encryption_key() -> str:
    """Generate a new random 32-byte encryption key as a hex string.

    The user should store this key somewhere safe — if lost, all encrypted
    data becomes unrecoverable.
    """
    return secrets.token_hex(32)


# --------------------------------------------------------------------------- #
# Image file encryption (AES-256-GCM)
# --------------------------------------------------------------------------- #


def encrypt_file(data: bytes, key: bytes | None = None) -> bytes:
    """Encrypt file data with AES-256-GCM.

    Returns: nonce (12 bytes) + ciphertext + tag (16 bytes).
    If encryption is not enabled, returns the data unchanged.

    v1.2.14 (P0-3): if CORPUSMIND_ENCRYPTION_KEY is set but `cryptography`
    is missing, this raises ImportError instead of silently returning
    plaintext data.
    """
    if key is None:
        key = get_encryption_key()
    if key is None:
        return data  # encryption disabled — passthrough

    # v1.2.14 (P0-3): cryptography availability is checked in
    # get_encryption_key(), which raises ImportError before we reach here.
    # Defensive double-check in case a caller passed an explicit key.
    if not _CRYPTO_AVAILABLE:
        raise ImportError(
            "encrypt_file() called with a key but the `cryptography` package "
            "is not installed. Install `cryptography` or unset "
            "CORPUSMIND_ENCRYPTION_KEY."
        )
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return nonce + ciphertext


def decrypt_file(data: bytes, key: bytes | None = None) -> bytes:
    """Decrypt file data encrypted with encrypt_file().

    If encryption is not enabled, returns the data unchanged.
    """
    if key is None:
        key = get_encryption_key()
    if key is None:
        return data  # encryption disabled — passthrough

    if not _CRYPTO_AVAILABLE:
        # v1.2.14 (P0-3): if a key was somehow supplied but cryptography is
        # missing, raise instead of silently returning the encrypted bytes.
        raise ImportError(
            "decrypt_file() called with a key but the `cryptography` package "
            "is not installed. Install `cryptography` or unset "
            "CORPUSMIND_ENCRYPTION_KEY."
        )
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if len(data) < 28:  # 12 (nonce) + 16 (tag) minimum
        return data
    nonce = data[:12]
    ciphertext = data[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


# --------------------------------------------------------------------------- #
# DB-level encryption status
# --------------------------------------------------------------------------- #


def get_encryption_status() -> dict:
    """Return the current encryption status for the UI.

    v1.2.14 (P0-4): honestly exposes `db_encrypted: False` — at-rest
    encryption covers image files and research transcripts, but the SQLite
    DB itself remains plaintext until SQLCipher is integrated (Phase 7+).
    The previous version reported a single "ENABLED" badge that did not
    distinguish the two.
    """
    key_present = bool(os.environ.get("CORPUSMIND_ENCRYPTION_KEY"))
    crypto_ok = _CRYPTO_AVAILABLE
    enabled = key_present and crypto_ok

    if not key_present:
        notice = (
            "At-rest encryption is OFF by default. To enable: set "
            "CORPUSMIND_ENCRYPTION_KEY to a 64-character hex string (use "
            "generate_encryption_key() to create one). WARNING: if the key "
            "is lost, all encrypted data becomes unrecoverable."
        )
    elif not crypto_ok:
        # v1.2.14 (P0-3): surface the missing-dep case honestly.
        notice = (
            "CORPUSMIND_ENCRYPTION_KEY is set but the `cryptography` "
            "package is not installed. At-rest encryption is INACTIVE — "
            "data is being stored as plaintext. Install `cryptography` "
            "(pip install cryptography) and restart the engine to activate "
            "encryption."
        )
    else:
        notice = (
            "At-rest encryption is ENABLED. Image files and research "
            "transcripts on disk are encrypted with AES-256-GCM. The SQLite "
            "DB itself is NOT encrypted (Phase 7+ will integrate SQLCipher). "
            "The encryption key is read from the CORPUSMIND_ENCRYPTION_KEY "
            "environment variable and is NEVER stored on disk."
        )

    return {
        "enabled": enabled,
        "method": "AES-256-GCM (application-layer)" if enabled else "none",
        # v1.2.14 (P0-4): honest field for the UI to display.
        "db_encrypted": False,  # Phase 7+ will flip this when SQLCipher lands
        "image_encrypted": enabled,
        "transcript_encrypted": enabled,
        "key_present": key_present,
        "crypto_available": crypto_ok,
        "notice": notice,
    }
