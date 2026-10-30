"""Pasted text as a stand-in for an uploaded CSV file.

PastedFile has the two things the page states use from an rx.UploadFile (async read(), filename), so every
"from CSV" handler also works on text pasted into a box. The text can be tab, pipe, semicolon or comma
separated (tab first, so Excel pastes work). The header row is optional: without one, `columns` names the
columns in order; a single column list (numbers, emails, names) may also be separated by any of those characters.
"""

import csv
import io
import re

DELIMS = ("\t", "|", ";", ",")


def no_at(cells: list[str]) -> bool:
    """Header test for email lists: a header row has no @ in it."""
    return not any("@" in c for c in cells)


def no_at_or_digit(cells: list[str]) -> bool:
    """Header test for number or email lists: a header row has no @ and no digits."""
    return not any("@" in c or any(ch.isdigit() for ch in c) for c in cells)


def _split(line: str, delim: str | None) -> list[str]:
    return [c.strip() for c in next(csv.reader([line], delimiter=delim or ","))]


def paste_to_csv(text: str, columns=(), markers=(), header_if=None, flatten=False, extra_prefix="",
                 item_split=r"[\t|;,]", delims=DELIMS) -> bytes:
    """CSV bytes (with a header row) from pasted text.

    columns      header to use when the pasted text has none; empty means the text always carries its header
    markers      a first line holding one of these cells (case-insensitive) is a header row
    header_if    alternative header test, called with the cells of the first line
    flatten      without a header, every separated item is its own row of the single column
    delims       column separators to look for, in order (leave out ";" when cells hold ;-separated lists)
    item_split   regex that separates the items of a flattened list (names may contain commas: use a tab only)
    extra_prefix cells beyond `columns` are named prefix1, prefix2, ... (for agent1, agent2 columns)
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("Paste some text first.")
    delim = next((d for d in delims if d in lines[0]), None)
    first = _split(lines[0], delim)
    if not columns:
        has_header = True
    elif header_if is not None:
        has_header = header_if(first)
    else:
        has_header = any(c.lower() in markers for c in first)
    if has_header:
        rows = [_split(ln, delim) for ln in lines]
    elif flatten:
        rows = [list(columns[:1])] + [[t.strip()] for ln in lines for t in re.split(item_split, ln) if t.strip()]
    else:
        body = [_split(ln, delim) for ln in lines]
        extra = max(len(r) for r in body) - len(columns) if extra_prefix else 0
        rows = [list(columns) + [f"{extra_prefix}{i}" for i in range(1, extra + 1)]] + body
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    return out.getvalue().encode("utf-8")


class PastedFile:
    """Duck-types rx.UploadFile for pasted text. Arguments are those of paste_to_csv."""

    filename = "pasted text"

    def __init__(self, text: str, **options):
        self._text, self._options = text, options

    async def read(self) -> bytes:
        return paste_to_csv(self._text, **self._options)
