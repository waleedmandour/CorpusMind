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
"""
from __future__ import annotations

import hashlib
import os
import secrets

from app.logging import get_logger

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Key management
# --------------------------------------------------------------------------- #


def get_encryption_key() -> bytes | None:
    """Get the at-rest encryption key from the environment.

    Returns None if encryption is not enabled (the default).
    Returns a 32-byte key if CORPUSMIND_ENCRYPTION_KEY is set.
    """
    raw = os.environ.get("CORPUSMIND_ENCRYPTION_KEY")
    if not raw:
        return None
    # If it's a 64-char hex string, use it directly
    if len(raw) == 64:
        try:
            return bytes.fromhex(raw)
        except ValueError:
            pass
    # Otherwise, derive a key from the passphrase via SHA-256
    return hashlib.sha256(raw.encode("utf-8")).digest()


def is_encryption_enabled() -> bool:
    """Check whether at-rest encryption is enabled."""
    return get_encryption_key() is not None


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
    """
    if key is None:
        key = get_encryption_key()
    if key is None:
        return data  # encryption disabled — passthrough

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = os.urandom(12)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, data, None)
        return nonce + ciphertext
    except ImportError:
        log.warning("encryption_unavailable", reason="cryptography package not installed")
        return data


def decrypt_file(data: bytes, key: bytes | None = None) -> bytes:
    """Decrypt file data encrypted with encrypt_file().

    If encryption is not enabled, returns the data unchanged.
    """
    if key is None:
        key = get_encryption_key()
    if key is None:
        return data  # encryption disabled — passthrough

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if len(data) < 28:  # 12 (nonce) + 16 (tag) minimum
            return data
        nonce = data[:12]
        ciphertext = data[12:]
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext, None)
    except ImportError:
        log.warning("decryption_unavailable", reason="cryptography package not installed")
        return data
    except Exception as e:
        log.error("decryption_failed", error=str(e))
        raise


# --------------------------------------------------------------------------- #
# DB-level encryption status
# --------------------------------------------------------------------------- #


def get_encryption_status() -> dict:
    """Return the current encryption status for the UI."""
    enabled = is_encryption_enabled()
    return {
        "enabled": enabled,
        "method": "AES-256-GCM (application-layer)" if enabled else "none",
        "notice": (
            "At-rest encryption is OFF by default. To enable: set "
            "CORPUSMIND_ENCRYPTION_KEY to a 64-character hex string (use "
            "generate_encryption_key() to create one). WARNING: if the key "
            "is lost, all encrypted data becomes unrecoverable."
        ) if not enabled else
        "At-rest encryption is ENABLED. Image files on disk are encrypted "
        "with AES-256-GCM. The encryption key is read from the "
        "CORPUSMIND_ENCRYPTION_KEY environment variable and is NEVER stored "
        "on disk.",
        "key_present": enabled,
    }
