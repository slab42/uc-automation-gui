"""Application settings kept in `webui/app_settings.json` (per machine, git-ignored). Plain Python, no Reflex imports."""

import json
import os
import tempfile
import threading

from .paths import WEBUI_ROOT

SETTINGS_PATH = WEBUI_ROOT / "app_settings.json"

DEFAULTS = {
    "log_retention_days": 90,   # delete logs older than this many days (0 = keep forever)
    "log_max_mb": 2048,         # delete the oldest logs while all logs together exceed this (0 = no limit)
}
_lock = threading.Lock()


def load() -> dict[str, int]:
    """The saved settings with defaults filled in. A missing or damaged file gives the defaults."""
    out = dict(DEFAULTS)
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    if isinstance(saved, dict):
        for key in DEFAULTS:
            value = saved.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                out[key] = value
    return out


def save(values: dict[str, int]) -> dict[str, int]:
    """Merge known keys into the file (written atomically). Returns what is now saved."""
    with _lock:
        merged = load()
        for key in DEFAULTS:
            if key in values:
                merged[key] = int(values[key])
        fd, tmp = tempfile.mkstemp(dir=SETTINGS_PATH.parent, prefix=".app_settings.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(merged, f, indent=2)
                f.write("\n")
            os.replace(tmp, SETTINGS_PATH)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    return merged
