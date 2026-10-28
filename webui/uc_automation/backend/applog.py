"""Operation logs for the web app: one plain text file per operation in `webui/logs/`.

Same line format as the CLI (`setup/logger.py`) and the same file name pattern
(`<YYYY-MM-DD_HH-MM-SS>-<slug>.log`). Each log starts with "<Title> - Started" and ends with
"<Title> - Completed". Never log passwords.
"""

import logging
import re
import threading
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

from .paths import LOG_DIR

_FORMAT = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S")
_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:-\d+)?-[A-Za-z0-9._-]+\.log$")
_lock = threading.Lock()
VIEW_LIMIT = 1_000_000  # bytes shown on screen; export always gives the whole file


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-").lower() or "log"


class OpLog:
    """One operation's log. Call `close()` when the operation ends (use try/finally)."""

    def __init__(self, title: str, slug: str):
        self.title = title
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        with _lock:  # two operations in the same second must not share a file
            n = 0
            while True:
                suffix = f"-{n}" if n else ""
                self.path = LOG_DIR / f"{stamp}{suffix}-{_slug(slug)}.log"
                if not self.path.exists():
                    self.path.touch()
                    break
                n += 1
        self._logger = logging.getLogger(f"webui.{self.path.name}")
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False
        self._handler = logging.FileHandler(self.path, encoding="utf-8")
        self._handler.setFormatter(_FORMAT)
        self._logger.addHandler(self._handler)
        self._closed = False
        self.info(f"{title} - Started")

    def info(self, msg: str) -> None:
        self._logger.info(msg)

    def warning(self, msg: str) -> None:
        self._logger.warning(msg)

    def error(self, msg: str) -> None:
        self._logger.error(msg)

    def debug(self, msg: str) -> None:
        self._logger.debug(msg)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.info(f"{self.title} - Completed")
        self._logger.removeHandler(self._handler)
        self._handler.close()


# --- reading (Logs page) ---


def _safe_path(name: str) -> Path | None:
    """Resolve a client-supplied log name; None unless it is a real log file inside LOG_DIR."""
    if not _NAME_RE.match(name):
        return None
    p = LOG_DIR / name
    return p if p.is_file() else None


def _entry(p: Path) -> dict[str, str]:
    stem = p.name[:-4]
    m = re.match(r"^(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})(?:-\d+)?-(.+)$", stem)
    if m:
        when = f"{m.group(1)} {m.group(2)}:{m.group(3)}:{m.group(4)}"
        what = m.group(5)
    else:
        when, what = "", stem
    size = p.stat().st_size
    return {
        "name": p.name,
        "when": when,
        "what": what,
        "size": f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B",
    }


def list_logs(query: str = "") -> list[dict[str, str]]:
    """All logs, newest first. A query matches the file name or anything inside the file."""
    if not LOG_DIR.is_dir():
        return []
    q = query.strip().lower()
    out = []
    for p in sorted(LOG_DIR.glob("*.log"), reverse=True):
        if not _NAME_RE.match(p.name):
            continue
        if q and q not in p.name.lower():
            try:
                if q not in p.read_text(encoding="utf-8", errors="replace").lower():
                    continue
            except OSError:
                continue
        out.append(_entry(p))
    return out


def parse_logs(query: str = "", limit: int = 200) -> list[str]:
    """The last `limit` log lines (oldest first) across all logs, only those containing the query."""
    if not LOG_DIR.is_dir():
        return []
    q = query.strip().lower()
    found: list[str] = []
    for p in sorted(LOG_DIR.glob("*.log"), reverse=True):  # newest file first
        if not _NAME_RE.match(p.name):
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            if line.strip() and (not q or q in line.lower()):
                found.append(line)
                if len(found) >= limit:
                    return found[::-1]
    return found[::-1]


def read_log(name: str) -> tuple[str, bool]:
    """(text, truncated). Raises FileNotFoundError for an unknown name."""
    p = _safe_path(name)
    if p is None:
        raise FileNotFoundError(name)
    with p.open("rb") as f:
        data = f.read(VIEW_LIMIT + 1)
    return data[:VIEW_LIMIT].decode("utf-8", errors="replace"), len(data) > VIEW_LIMIT


def export_logs(names: list[str]) -> tuple[str, bytes, str]:
    """(file name, data, mime type): the .log itself for one, a zip for several."""
    paths = [p for p in (_safe_path(n) for n in names) if p is not None]
    if not paths:
        raise FileNotFoundError("None of the selected logs exist any more.")
    if len(paths) == 1:
        return paths[0].name, paths[0].read_bytes(), "text/plain"
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            z.write(p, p.name)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"uc-automation-logs-{stamp}.zip", buf.getvalue(), "application/zip"
