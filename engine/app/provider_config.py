"""Runtime provider configuration overrides (v1.2.14-8, r8 — P0-3b).

Small runtime settings (currently the LM Studio base URL and its optional
API key) are persisted as JSON under
``<data_dir>/provider-config/settings.json`` and re-applied onto the
process Settings at engine startup, so a custom LM Studio port survives an
app restart (the desktop sidecar's environment is fixed at spawn time —
env vars alone could not express "the user changed the port in Settings").

Privacy posture: the file lives in the user's OWN data directory on the
engine machine (same place as the server-mode classroom config), it is
never served to the browser (the public /settings endpoint exposes only
the base URL, never the key), and the key is never echoed back by the
config endpoint either.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from app.logging import get_logger

log = get_logger(__name__)

_LOCK = threading.Lock()
_REL_PATH = "provider-config/settings.json"

# Only these Settings faces may be overridden at runtime. Keeping the set
# explicit stops a future caller from persisting something unexpected
# (e.g. a data_dir change) through this channel.
ALLOWED_KEYS = ("lmstudio_base_url", "lmstudio_api_key")


def _path(settings: Any) -> Path:
    return Path(settings.data_dir).expanduser() / _REL_PATH


def load_persisted_overrides() -> dict[str, str]:
    """Read the persisted overrides (empty dict when absent/corrupt)."""
    try:
        p = _path(get_settings_like())
    except Exception:
        return {}
    return _read_file(p)


def get_settings_like() -> Any:
    """Resolve the Settings-like object used for the data_dir path.

    Kept as a function so tests can monkeypatch the resolution; the default
    imports the real lru-cached settings lazily (no import cycle at module
    load: app.settings imports pydantic only).
    """
    from app.settings import get_settings

    return get_settings()


def _read_file(p: Path) -> dict[str, str]:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.warning("provider_config_unreadable", path=str(p), error=str(e))
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if k in ALLOWED_KEYS}


def persist_overrides(updates: dict[str, str]) -> None:
    """Merge ``updates`` (filtered to ALLOWED_KEYS) into the override file."""
    clean = {k: str(v) for k, v in updates.items() if k in ALLOWED_KEYS}
    if not clean:
        return
    with _LOCK:
        settings = get_settings_like()
        p = _path(settings)
        p.parent.mkdir(parents=True, exist_ok=True)
        current = _read_file(p)
        current.update(clean)
        p.write_text(json.dumps(current, indent=2), encoding="utf-8")
        log.info("provider_config_persisted", keys=sorted(clean.keys()))


def clear_overrides() -> None:
    """Remove every persisted override (LM Studio config reset)."""
    with _LOCK:
        p = _path(get_settings_like())
        try:
            p.unlink()
            log.info("provider_config_cleared", path=str(p))
        except FileNotFoundError:
            pass
        except Exception as e:
            log.warning("provider_config_clear_failed", path=str(p), error=str(e))


def apply_persisted_overrides(settings: Any) -> int:
    """Apply the persisted overrides onto a Settings instance (startup).

    Returns the number of faces applied. Unknown/forbidden keys in the file
    are ignored (see ALLOWED_KEYS).
    """
    overrides = _read_file(_path(settings))
    applied = 0
    for key in ALLOWED_KEYS:
        if key in overrides:
            setattr(settings, key, overrides[key])
            applied += 1
    if applied:
        log.info("provider_config_applied", applied=applied, keys=sorted(overrides.keys()))
    return applied
