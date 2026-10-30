"""Helpers shared by the RedSky tool backends: CSV rows, yes/no and list cells, location names, and the
spec classes that describe each add tool and each check tool (one definition drives the form, the CSV
template, the parser and the run loop)."""

import csv
import io
from dataclasses import dataclass
from typing import Callable

from .redsky_api import RedskyClient, RedskyError

LOCATION_HELP = ("Matched by name, case-insensitively. If the same name exists in more than one Building, "
                 "use 'Building / Location'.")


@dataclass(frozen=True)
class Field:
    key: str  # CSV column name
    label: str
    hint: str = ""
    required: bool = False
    options: str = ""  # key of the lookups list offered as suggestions ('' = none)
    yesno: bool = False  # Not Set / Yes / No select instead of a text box
    default: str = ""


def no_prepare(client: RedskyClient) -> None:
    """Default AddSpec.prepare. A named function, not a lambda: specs are held by the states, which get pickled."""
    return None


@dataclass(frozen=True)
class AddSpec:
    slug: str
    title: str  # menu / page title, e.g. "Add Buildings"
    noun: str  # "building"
    blurb: str
    fields: tuple[Field, ...]
    add: Callable[[RedskyClient, object, dict[str, str]], str]  # (client, context, row) -> detail
    prepare: Callable[[RedskyClient], object] = no_prepare  # one-time lookups for a run
    lookups: Callable[[RedskyClient], dict[str, list[str]]] | None = None  # suggestions for the single form
    label_keys: tuple[str, ...] = ()  # row columns joined for the result label (default: first column)
    csv_note: str = ""
    example: str = ""

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(f.key for f in self.fields)


@dataclass(frozen=True)
class CheckSpec:
    slug: str
    title: str
    noun: str  # "building"
    blurb: str
    columns: tuple[tuple[str, str], ...]  # (row key, header), also the CSV columns
    run: Callable[[RedskyClient], tuple[int, list[dict[str, str]]]]  # -> (items checked, problem rows)
    ok_message: str = ""


def read_rows(data: bytes, width: int) -> list[list[str]]:
    """Data rows of a CSV (the header row is skipped, as in the CLI), stripped and padded to `width`."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("The file is not UTF-8 text.")
    reader = csv.reader(io.StringIO(text, newline=""))
    next(reader, None)
    rows = [[c.strip() for c in row] + [""] * width for row in reader if any(c.strip() for c in row)]
    if not rows:
        raise ValueError("The CSV has no data rows.")
    return [r[:width] for r in rows]


def parse_bool(text: str) -> bool | None:
    """True/False for yes/no style text, None when blank, 'not set' or unrecognized."""
    value = text.strip().lower()
    if value in ("yes", "y", "true", "1"):
        return True
    if value in ("no", "n", "false", "0"):
        return False
    return None


def split_list(text: str) -> list[str]:
    """Items of a semicolon separated cell."""
    return [item.strip() for item in text.split(";") if item.strip()]


def normalize(text: str) -> str:
    """Lowercase and collapse whitespace for name comparison."""
    return " ".join(text.split()).lower()


def location_map(client: RedskyClient) -> dict[str, str | None]:
    """{lowercase key: location id}. Each location is keyed by its name and by 'building / name'. A name used in
    several Buildings maps to None (ambiguous) so it can only be addressed as 'building / name'."""
    found: dict[str, str | None] = {}
    for building, loc in client.list_all_locations():
        name = loc.get("name", "").strip().lower()
        keys = [name] + ([f"{building.strip().lower()} / {name}"] if building else [])
        for key in keys:
            found[key] = None if key in found else loc["id"]
    return found


def location_choices(client: RedskyClient) -> list[str]:
    """Location names for the single-entry suggestion list: 'Building / Location', or the name alone at org level."""
    names = {f"{b.strip()} / {loc.get('name', '').strip()}" if b else loc.get("name", "").strip()
             for b, loc in client.list_all_locations()}
    return sorted(n for n in names if n)


def resolve_location(locations: dict[str, str | None], text: str) -> str:
    """The location id for a name or 'Building / Location', or raise RedskyError."""
    key = " / ".join(part.strip() for part in text.split("/")).lower()
    if key not in locations:
        raise RedskyError(f"unknown location: '{text}'")
    if locations[key] is None:
        raise RedskyError(f"location name '{text}' is used in more than one Building, use 'Building / Location'")
    return locations[key]


def build_items(spec: AddSpec, client: RedskyClient, rows: list[list[str]]) -> list[tuple[str, Callable]]:
    """(label, callable) per row for RunMixin._run_items. A row missing a required value fails on its own."""
    context = spec.prepare(client)
    keys = spec.label_keys or spec.columns[:1]
    items = []
    for n, values in enumerate(rows, 1):
        row = dict(zip(spec.columns, values))
        label = " ".join(row[k] for k in keys if row.get(k)) or f"row {n}"

        def run(row=row):
            missing = [f.label for f in spec.fields if f.required and not row[f.key]]
            if missing:
                raise RedskyError("Required: " + ", ".join(missing))
            return spec.add(client, context, row)

        items.append((label, run))
    return items


def csv_bytes(header: list[str] | tuple[str, ...], rows: list[list[str]] = ()) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")
