"""Bridge the engine's stable PI resources folder onto persuasion-index's
own supported environment overrides (v1.2.9).

WHY THIS EXISTS
---------------
The Discourse → Persuasion Index lens is scored by the pinned
``persuasion-index==0.3.0`` package. Its 15 dimensions run on the
package's bundled lexicons, but five optional resources refine specific
subfeatures:

  - single_word_concreteness  (Brysbaert et al. 2014 ratings, .xlsx)
  - multiword_concreteness    (2-word expression ratings, .csv)
  - liwc                      (licensed LIWC dictionary, legacy .dic)
  - nrc_vad                   (NRC-VAD-Lexicon v2.1 unigrams, .txt)
  - spacy_model               (en_core_web_sm — always bundled by us)

The four data files are license-restricted: the provider terms forbid
redistribution, so CorpusMind can never ship them (same compliance
stance as the NRC EmoLex sentiment lexicons, v1.2.8). persuasion-index
already resolves each of them through its OWN documented env vars —
``PI_CONCRETENESS_FILE``, ``PI_MWE_CONCRETENESS_FILE``,
``PI_LIWC_FILE``, ``PI_NRC_VAD_FILE`` — falling back to files inside the
installed package tree (``helper_features/``), which for a frozen
PyInstaller bundle is ``_internal\\helper_features\\...``: a directory
that is wiped on every app update and that a desktop user cannot
realistically edit.

THE BRIDGE
----------
At engine startup, :func:`apply_pi_resource_env` resolves a single
user-owned, update-surviving folder:

  1. ``CORPUSMIND_PI_RESOURCES_DIR`` when set;
  2. otherwise ``<data_dir>/pi-resources/`` (e.g.
     ``C:\\Users\\<u>\\.corpusmind\\pi-resources`` on Windows,
     ``~/.corpusmind/pi-resources`` on macOS/Linux).

For each optional resource it then sets persuasion-index's env var —
unless the operator already set it — from, in priority order:

  1. the matching per-resource engine setting
     (``CORPUSMIND_PI_CONCRETENESS_FILE``, …);
  2. the expected canonical filename inside the resources folder.

``check_resources()`` in persuasion-index reads the environment at call
time, so once the bridge has run the health endpoint and the lens score
both see the user-installed files. Nothing here downloads anything and
nothing here accepts a license on the user's behalf — exactly the
compliance posture the persuasion-index authors chose.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Canonical on-disk layout of the resources folder, keyed by the
# persuasion-index env var each file satisfies. Values:
# (resource_key, expected_relative_path, official_source_url, license_note).
PI_RESOURCE_LAYOUT: dict[str, tuple[str, str, str, str]] = {
    "PI_CONCRETENESS_FILE": (
        "single_word_concreteness",
        "Brysbaert_concretness_dataset.xlsx",
        "https://biblio.ugent.be/publication/5774089",
        "Obtain from the official source (Brysbaert et al. 2014, "
        "supplemental data); not redistributed by CorpusMind or PI.",
    ),
    "PI_MWE_CONCRETENESS_FILE": (
        "multiword_concreteness",
        "MultiwordExpression_Concreteness_Ratings.csv",
        "https://osf.io/ksypa/",
        "Obtain from the authors' OSF repository; not redistributed by "
        "CorpusMind or PI.",
    ),
    "PI_LIWC_FILE": (
        "liwc",
        "en_liwc.txt",
        "https://www.liwc.app/download",
        "A valid LIWC license is required (legacy .dic — LIWC-22 .dicx is "
        "not supported by PI 0.3.0). Do not redistribute the dictionary.",
    ),
    "PI_NRC_VAD_FILE": (
        "nrc_vad",
        str(Path("NRC-VAD-Lexicon-v2.1") / "Unigrams" / "unigrams-NRC-VAD-Lexicon-v2.1.txt"),
        "https://saifmohammad.com/WebPages/nrc-vad.html",
        "Non-commercial research/educational use; citation required; "
        "redistribution prohibited by the provider.",
    ),
}

# Engine-settings mirror of the same env vars (win over the folder layout).
_SETTING_TO_ENV: dict[str, str] = {
    "pi_concreteness_file": "PI_CONCRETENESS_FILE",
    "pi_mwe_concreteness_file": "PI_MWE_CONCRETENESS_FILE",
    "pi_liwc_file": "PI_LIWC_FILE",
    "pi_nrc_vad_file": "PI_NRC_VAD_FILE",
}


def pi_resources_root(settings: Any) -> Path:
    """The stable, user-owned folder optional PI resources are looked up in."""
    configured = (getattr(settings, "pi_resources_dir", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(settings.data_dir).expanduser() / "pi-resources"


def apply_pi_resource_env(settings: Any) -> dict[str, str]:
    """Set PI's own env vars from the engine settings / resources folder.

    Idempotent and non-destructive: a var the operator already set (or one
    resolved on a previous call) is left untouched. Returns the mapping of
    env vars that were SET by this call (not the pre-existing ones).
    """
    root = pi_resources_root(settings)
    applied: dict[str, str] = {}
    for setting_name, env_name in _SETTING_TO_ENV.items():
        if os.environ.get(env_name, "").strip():
            continue  # operator/explicit override wins — never stomp it
        explicit = (getattr(settings, setting_name, "") or "").strip()
        candidate: Path | None = None
        if explicit:
            candidate = Path(explicit).expanduser()
        else:
            expected = PI_RESOURCE_LAYOUT[env_name][1]
            folder_hit = root / expected
            if folder_hit.is_file():
                candidate = folder_hit
        if candidate is not None and candidate.is_file():
            os.environ[env_name] = str(candidate.resolve())
            applied[env_name] = os.environ[env_name]
    return applied


def install_hints(settings: Any) -> dict[str, dict[str, Any]]:
    """Per-resource, per-env "how to enable" metadata for the health panel.

    Shaped for the UI's Persuasion Index resource card: for every optional
    file-backed resource it reports the env var persuasion-index honours,
    the canonical filename to place in the resources folder, the official
    download source, the license note, and whether the file is currently
    resolvable (explicit setting or folder layout).
    """
    root = pi_resources_root(settings)
    hints: dict[str, dict[str, Any]] = {}
    for env_name, (key, expected, source_url, license_note) in PI_RESOURCE_LAYOUT.items():
        explicit = ""
        for setting_name, candidate_env in _SETTING_TO_ENV.items():
            if candidate_env == env_name:
                explicit = (getattr(settings, setting_name, "") or "").strip()
                break
        env_now = os.environ.get(env_name, "").strip()
        folder_path = root / expected
        resolvable = bool(explicit and Path(explicit).expanduser().is_file()) or (
            not explicit and folder_path.is_file()
        )
        hints[key] = {
            "env_var": env_name,
            "engine_setting": f"CORPUSMIND_{setting_name.upper()}",
            "filename": expected,
            "folder": str(root),
            "source_url": source_url,
            "license_note": license_note,
            "resolvable": resolvable,
            "resolved_from": (
                "engine_setting" if explicit else ("resources_folder" if folder_path.is_file() else "")
            ),
            # Surfaces the env value PI will actually use, when one is set.
            "env_value": env_now or None,
        }
    return hints


def resources_dir_hint(settings: Any) -> str:
    """The folder path shown to the user in the UI / docs."""
    return str(pi_resources_root(settings))
