"""Operation logs for the web app: one plain text file per operation in `webui/logs/`.

Same line format as the CLI (`setup/logger.py`) and the same file name pattern
(`<YYYY-MM-DD_HH-MM-SS>-<slug>.log`). Each log starts with "<Title> - Started" and ends with
"<Title> - Completed". Never log passwords.
"""

import logging
import re
import threading
import time
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

from . import app_settings
from .paths import LOG_DIR

_FORMAT = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S")
_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:-\d+)?-[A-Za-z0-9._-]+\.log$")
_lock = threading.Lock()
LINE_LIMIT = 1000  # lines read from the end of a log for the viewer and for searches; export gives the whole file
PRUNE_EVERY = 600  # seconds between automatic prunes (the first log of a run, then at most this often)
_open_paths: set[Path] = set()  # logs being written right now (never pruned)
_last_prune = 0.0


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
                    _open_paths.add(self.path)
                    break
                n += 1
        prune_if_due()
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
        _open_paths.discard(self.path)


# --- pruning ---


def prune_logs() -> int:
    """Delete logs past the retention settings: older than log_retention_days, then the oldest ones while the
    total size is over log_max_mb. 0 turns a limit off. Logs still being written are kept. Returns how many went."""
    if not LOG_DIR.is_dir():
        return 0
    cfg = app_settings.load()
    files = []
    for p in LOG_DIR.glob("*.log"):
        if _NAME_RE.match(p.name) and p not in _open_paths:
            try:
                st = p.stat()
            except OSError:
                continue
            files.append((st.st_mtime, st.st_size, p))
    files.sort()  # oldest first
    doomed: list[tuple[float, int, Path]] = []
    days = cfg["log_retention_days"]
    if days:
        cutoff = time.time() - days * 86400
        doomed = [f for f in files if f[0] < cutoff]
        files = files[len(doomed):]
    limit = cfg["log_max_mb"] * 1024 * 1024
    if limit:
        total = sum(f[1] for f in files)
        while files and total > limit:
            f = files.pop(0)
            total -= f[1]
            doomed.append(f)
    removed = 0
    for _mtime, _size, p in doomed:
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def prune_if_due() -> None:
    """prune_logs() at most once every PRUNE_EVERY seconds. Never raises: a prune problem must not stop an operation."""
    global _last_prune
    now = time.monotonic()
    with _lock:
        if _last_prune and now - _last_prune < PRUNE_EVERY:
            return
        _last_prune = now
    try:
        prune_logs()
    except Exception:
        pass


# --- reading (Logs page) ---


def _tail_lines(p: Path, n: int = LINE_LIMIT) -> tuple[list[str], bool]:
    """(the last n lines of a log, whether earlier lines were left out). Reads blocks from the end, so a big file
    costs no more than a small one."""
    block = 64 * 1024
    with p.open("rb") as f:
        f.seek(0, 2)
        pos = f.tell()
        data = b""
        while pos > 0 and data.count(b"\n") <= n:
            step = min(block, pos)
            pos -= step
            f.seek(pos)
            data = f.read(step) + data
    lines = data.decode("utf-8", errors="replace").splitlines()
    if pos > 0:
        lines = lines[1:]  # the first line is probably cut in half
    return lines[-n:], pos > 0 or len(lines) > n


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
                if q not in "\n".join(_tail_lines(p)[0]).lower():
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
            lines = _tail_lines(p)[0]
        except OSError:
            continue
        for line in reversed(lines):
            if line.strip() and (not q or q in line.lower()):
                found.append(line)
                if len(found) >= limit:
                    return found[::-1]
    return found[::-1]


def read_log(name: str) -> tuple[str, bool]:
    """(text, truncated): the last LINE_LIMIT lines. Raises FileNotFoundError for an unknown name."""
    p = _safe_path(name)
    if p is None:
        raise FileNotFoundError(name)
    lines, truncated = _tail_lines(p)
    return "\n".join(lines), truncated


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
