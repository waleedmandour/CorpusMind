"""Configure Windows code signing for the Tauri build (release CI helper).

Writes ``desktop/src-tauri/signing-override.json`` — a Tauri ``--config``
override that adds Authenticode signing for the NSIS installer, the MSI, and
the NSIS uninstaller — and prints the chosen mode. Tauri v2 merges ``--config``
files over ``tauri.conf.json``.

WHY
---
Unsigned Windows installers trigger the Microsoft Defender SmartScreen
"Windows protected your PC" screen for every new user. LancsBox — the closest
peer corpus tool — documents a click-through for that screen (its manual says
to "agree to security warnings"; its help page says to "allow #LancsBox to run
by adjusting security settings"). CorpusMind instead wires REAL signing into
the release pipeline so the prompt disappears once a signing identity is
configured, with the documented click-through as the interim fallback.

Modes (chosen by the caller via CM_SIGN_MODE; the release workflow sets it
from which repository secrets are present):

``trusted``
    Azure Trusted Signing (Microsoft's managed signing service — see
    docs/BUILD_GUIDE.md §5.9). The bundler executes ``signCommand`` for every
    artifact; the CLI talks to the Microsoft-operated CA whose certificates
    SmartScreen recognises. Requires the artifact-signing CLI on PATH and the
    standard Azure app-credential env vars (AZURE_CLIENT_ID / AZURE_TENANT_ID
    / AZURE_CLIENT_SECRET), which the workflow maps from CM_AZURE_* secrets.

``pfx``
    Classic Authenticode: the workflow has already imported a PFX into the
    CurrentUser\\My store; this mode only needs the certificate THUMBPRINT
    plus a timestamp server. Tauri signs with signtool using the store cert.

``none``
    No signing configured (pre-signing behaviour). No file is written; the
    caller is expected to surface a build-summary warning so the gap stays
    visible.

Exit codes: 0 on success (including mode "none" — absence of credentials is a
legitimate state), 1 on a misconfiguration (mode set but its inputs missing).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Default RFC 3161 timestamp server. A timestamp keeps signatures valid after
# the certificate expires — never sign releases without one.
DEFAULT_TIMESTAMP_URL = "http://timestamp.digicert.com"

# Where the override is written (relative to the repo root this script
# resolves from, so it works both locally and in CI).
_REPO = Path(__file__).resolve().parent.parent
_OUT = _REPO / "desktop" / "src-tauri" / "signing-override.json"


def _require(mode: str, keys: list[str]) -> dict[str, str]:
    """Return {key: value} for every required key, or fail with a clear message."""
    missing = [k for k in keys if not os.environ.get(k)]
    if missing:
        print(
            f"ERROR: CM_SIGN_MODE={mode} requires env vars: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)
    return {k: os.environ[k] for k in keys}


def main() -> None:
    mode = (os.environ.get("CM_SIGN_MODE") or "none").strip().lower()

    if mode == "none":
        # Make sure a stale override from a previous run can never leak into
        # an unsigned build.
        _OUT.unlink(missing_ok=True)
        print("mode=none")
        return

    if mode == "trusted":
        vals = _require(
            mode,
            ["CM_TS_ENDPOINT", "CM_TS_ACCOUNT", "CM_TS_PROFILE"],
        )
        description = os.environ.get("CM_TS_DESCRIPTION") or "CorpusMind installer"
        # artifact-signing-cli: https://v2.tauri.app/distribute/sign/windows/
        # %1 is expanded by tauri-bundler to the file being signed.
        sign_command = (
            "artifact-signing-cli"
            f" -e {vals['CM_TS_ENDPOINT']}"
            f" -a {vals['CM_TS_ACCOUNT']}"
            f" -c {vals['CM_TS_PROFILE']}"
            f" -d {description}"
            " %1"
        )
        override = {
            "bundle": {
                "windows": {
                    "signCommand": sign_command,
                }
            }
        }

    elif mode == "pfx":
        vals = _require(mode, ["CM_WIN_THUMBPRINT"])
        timestamp_url = (
            os.environ.get("CM_WIN_TIMESTAMP_URL") or DEFAULT_TIMESTAMP_URL
        )
        override = {
            "bundle": {
                "windows": {
                    "certificateThumbprint": vals["CM_WIN_THUMBPRINT"],
                    "digestAlgorithm": "sha256",
                    "timestampUrl": timestamp_url,
                }
            }
        }

    else:
        print(
            f"ERROR: unknown CM_SIGN_MODE={mode!r} (expected trusted|pfx|none)",
            file=sys.stderr,
        )
        sys.exit(1)

    _OUT.write_text(json.dumps(override, indent=2) + "\n", encoding="utf-8")
    print(f"mode={mode}")
    print(f"wrote {_OUT.relative_to(_REPO)}")


if __name__ == "__main__":
    main()
