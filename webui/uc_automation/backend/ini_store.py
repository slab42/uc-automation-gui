"""
Comment-preserving editor for .env/credentials.env (adapted from gui/backend/ini_editor.py).

configparser would rewrite the whole file and drop every comment, so the
Settings page edits the file line by line instead: existing lines are kept
exactly as they are, only the requested keys inside the requested section
are changed, and new keys/sections are appended in place.

Secret values (password, api_token, ...) are never returned by this module's
read helpers - only whether they are set.
"""

import os
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SECRET_KEYS = {"password", "api_token", "token", "secret"}
SERVICES = ("CUCM", "CUC", "CUBE", "WEBEX", "REDSKY")

_SECTION_RE = re.compile(r'^\s*\[([^\]]+)\]\s*$')
_KV_RE = re.compile(r'^\s*([^=:#;\s][^=:]*?)\s*[=:]\s*(.*?)\s*$')
_SECTION_NAME_RE = re.compile(r'^(CUCM|CUC|CUBE|WEBEX|REDSKY):([A-Za-z0-9._-]+)$')


def validate_section_name(section: str) -> Tuple[str, str]:
    """Return (service, identifier) or raise ValueError."""
    m = _SECTION_NAME_RE.match(section or "")
    if not m:
        raise ValueError(
            "Section must look like SERVICE:identifier where SERVICE is one of "
            "CUCM, CUC, CUBE, WEBEX, REDSKY and identifier uses letters, digits, '.', '_' or '-'.")
    return m.group(1), m.group(2)


def _read_lines(path: Path) -> List[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)


def _section_bounds(lines: List[str], section: str) -> Optional[Tuple[int, int]]:
    """Return (header_index, end_index_exclusive) of a section, or None."""
    start = None
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line)
        if m:
            if start is not None:
                return start, i
            if m.group(1).strip() == section:
                start = i
    if start is not None:
        return start, len(lines)
    return None


def _parse_sections(lines: List[str]) -> Dict[str, Dict[str, str]]:
    sections: Dict[str, Dict[str, str]] = {}
    current = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        m = _SECTION_RE.match(line)
        if m:
            current = m.group(1).strip()
            sections.setdefault(current, {})
            continue
        if current is None:
            continue
        kv = _KV_RE.match(line)
        if kv:
            sections[current][kv.group(1).strip().lower()] = kv.group(2)
    return sections


def read_sections(path: Path) -> List[dict]:
    """Public, secret-free view of every SERVICE:identifier section."""
    result = []
    for name, kv in _parse_sections(_read_lines(path)).items():
        try:
            service, identifier = validate_section_name(name)
        except ValueError:
            continue  # ignore sections that are not credential sections
        fields = {k: v for k, v in kv.items() if k not in SECRET_KEYS}
        secrets = {k: bool(v) for k, v in kv.items() if k in SECRET_KEYS}
        result.append({
            "section": name,
            "service": service,
            "identifier": identifier,
            "fields": fields,
            "secrets": secrets,
        })
    order = {s: i for i, s in enumerate(SERVICES)}
    result.sort(key=lambda s: (order.get(s["service"], 99),
                               s["identifier"] != "default",
                               s["identifier"].lower()))
    return result


def _atomic_write(path: Path, lines: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def upsert_section(path: Path, section: str, values: Dict[str, Optional[str]]) -> None:
    """
    Set keys inside a section, creating the section at the end of the file if
    it does not exist. values maps key -> new value. A None value means
    "leave this key untouched". An empty string writes "key=" (blank).
    Unknown keys are appended at the end of the section block.
    """
    validate_section_name(section)
    lines = _read_lines(path)
    todo = {k.lower(): v for k, v in values.items() if v is not None}

    bounds = _section_bounds(lines, section)
    if bounds is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.append(f"[{section}]\n")
        for k, v in todo.items():
            lines.append(f"{k}={v}\n")
        _atomic_write(path, lines)
        return

    start, end = bounds
    for i in range(start + 1, end):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith(("#", ";")):
            continue
        kv = _KV_RE.match(line)
        if not kv:
            continue
        key = kv.group(1).strip().lower()
        if key in todo:
            lines[i] = f"{key}={todo.pop(key)}\n"

    # Append keys the section did not have yet, just after the last
    # non-blank line of the block so trailing blank separators stay put.
    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    new_lines = [f"{k}={v}\n" for k, v in todo.items()]
    lines[insert_at:insert_at] = new_lines
    _atomic_write(path, lines)


def delete_section(path: Path, section: str) -> bool:
    """Remove a section and its keys. Returns False if it did not exist."""
    validate_section_name(section)
    lines = _read_lines(path)
    bounds = _section_bounds(lines, section)
    if bounds is None:
        return False
    start, end = bounds
    # Also drop one run of blank lines directly above the header so we do
    # not leave a double gap behind.
    while start > 0 and not lines[start - 1].strip():
        start -= 1
    del lines[start:end]
    if lines and lines[0].strip() == "" :
        lines.pop(0)
    _atomic_write(path, lines)
    return True


def read_section(path: Path, section: str) -> Dict[str, str]:
    """Backend-only: every key of one section, secrets included. Never send this to the browser."""
    return _parse_sections(_read_lines(path)).get(section, {})
