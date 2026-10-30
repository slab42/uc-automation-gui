"""RedSky Import Precheck: do the Buildings, Locations or Private IP ranges of an import list already exist?"""

import csv
import io
import ipaddress
import re

from .redsky_api import RedskyClient, RedskyError
from .redsky_common import normalize

KINDS = ("Buildings", "Locations", "Private IPs")
BUILDING_COLUMNS = (("name", "Building"), ("address", "Address"), ("status", "Status"), ("detail", "Conflicts With"))
LOCATION_COLUMNS = (("name", "Location"), ("status", "Status"))
IP_COLUMNS = (("name", "Name"), ("status", "Status"), ("building", "Building"), ("address", "Address"),
              ("detail", "Location"), ("range", "Range"))
_HEADERS = {"name", "building", "building name", "buildingname", "location", "location name",
            "ip", "ip range", "range", "ipaddresslow", "ip address low", "ip low", "fulladdress", "full address",
            "address"}


def columns(kind: str) -> tuple[tuple[str, str], ...]:
    return {"Buildings": BUILDING_COLUMNS, "Locations": LOCATION_COLUMNS}.get(kind, IP_COLUMNS)


def _entry(cells: list[str], kind: str) -> tuple[str, str] | None:
    """(name, second) from the cells of one input line: the address of a Building, or the Building of a Location
    (which may also be written 'Building / Location')."""
    cells = [c.strip() for c in cells]
    if not cells or not cells[0]:
        return None
    if kind == "Private IPs":  # low and high in two cells, as 'low-high', or one address or CIDR block
        tokens = [t for c in cells for t in re.split(r"[\s|,]+|-", c) if t]
        return tokens[0], (tokens[1] if len(tokens) > 1 else "")
    name, building = cells[0], (cells[1] if len(cells) > 1 else "")
    if kind == "Locations" and not building and "/" in name:
        building, _, name = (p.strip() for p in name.partition("/"))
    return name, building


def _drop_header(lines: list[list[str]]) -> list[list[str]]:
    if lines and normalize(lines[0][0]) in _HEADERS:
        return lines[1:]
    return lines


def parse_text(text: str, kind: str) -> list[tuple[str, str]]:
    """One entry per line. Columns are separated by a tab or |, so names may contain commas."""
    lines = []
    for line in text.splitlines():
        delim = "\t" if "\t" in line else "|" if "|" in line else None
        lines.append(line.split(delim) if delim else [line])
    return [e for e in (_entry(c, kind) for c in _drop_header(lines)) if e]


def parse_csv(data: bytes, kind: str) -> list[tuple[str, str]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("The file is not UTF-8 text.")
    lines = [r for r in csv.reader(io.StringIO(text, newline="")) if any(c.strip() for c in r)]
    return [e for e in (_entry(c, kind) for c in _drop_header(lines)) if e]


def _row(name: str, building: str, status: str, detail: str = "", range_: str = "", address: str = "") -> dict[str, str]:
    return {"name": name, "building": building, "status": status, "detail": detail, "range": range_,
            "address": address}


_ABBREVIATIONS = {"street": "st", "avenue": "ave", "road": "rd", "drive": "dr", "boulevard": "blvd", "lane": "ln",
                  "court": "ct", "suite": "ste", "north": "n", "south": "s", "east": "e", "west": "w", "usa": "",
                  "united": "", "states": "", "america": ""}


def normalize_address(text: str) -> str:
    """Lowercase, punctuation removed, common street words abbreviated, for address comparison."""
    words = re.sub(r"[^\w\s]", " ", text.lower()).split()
    return " ".join(w for w in (_ABBREVIATIONS.get(w, w) for w in words) if w)


def same_address(a: str, b: str) -> bool:
    """Equal after normalizing, or one is the other without its trailing part (RedSky adds city, state, zip, country)."""
    a, b = normalize_address(a), normalize_address(b)
    if not a or not b:
        return False
    short, long_ = sorted((a, b), key=len)
    return long_ == short or long_.startswith(short + " ")


_ADDRESS_KEYS = ("fullAddress", "normalizedAddress", "address", "streetAddress", "addressLine")


def building_address(b: dict) -> str:
    """The address text of a Building record, whichever field RedSky puts it in ('' when none is recognized)."""
    for key in _ADDRESS_KEYS:
        value = b.get(key)
        if isinstance(value, dict):
            value = (value.get("normalizedAddress") or value.get("fullAddress")
                     or " ".join(str(value.get(k, "")) for k in ("streetAddress", "city", "state", "zip")))
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def precheck_buildings(client: RedskyClient, entries: list[tuple[str, str]]) -> list[dict[str, str]]:
    """Per Building: does the name exist, then does the address belong to another Building.

    Exists (name found, address matches or none given), Exists - Address Differs, Exists - Address Conflict
    (the address is also on another Building, named in the last column), Address Conflict (new name, address
    already used), Not Found, Duplicate In List."""
    buildings = client.list_buildings()
    addresses = {id(b): building_address(b) for b in buildings}
    if any(addr for _n, addr in entries) and not any(addresses.values()):
        keys = ", ".join(sorted(buildings[0])) if buildings else "no buildings"
        raise RedskyError("RedSky returned no address for any Building, so addresses cannot be compared. "
                          f"Fields on a Building record: {keys}.")
    by_name: dict[str, dict] = {}
    for b in buildings:
        by_name.setdefault(normalize(b.get("name", "")), b)
    seen: set[tuple[str, str]] = set()
    rows = []
    for name, address in entries:
        key = (normalize(name), normalize_address(address))
        if key in seen:
            rows.append(_row(name, "", "Duplicate In List", address=address))
            continue
        seen.add(key)
        hit = by_name.get(key[0])
        others = [b for b in buildings if address and b is not hit and same_address(address, addresses[id(b)])]
        clash = ", ".join(dict.fromkeys(b.get("name", "").strip() for b in others))
        shown = address or (addresses[id(hit)] if hit else "")
        if hit is None:
            rows.append(_row(name, "", "Address Conflict", clash, address=shown) if others
                        else _row(name, "", "Not Found", address=shown))
        elif others:
            rows.append(_row(name, "", "Exists - Address Conflict", clash, address=shown))
        elif address and not same_address(address, addresses[id(hit)]):
            rows.append(_row(name, "", "Exists - Address Differs", address=shown))
        else:
            rows.append(_row(name, "", "Exists", address=shown))
    return rows


def precheck(client: RedskyClient, kind: str, entries: list[tuple[str, str]]) -> list[dict[str, str]]:
    """Locations: one result row per entry: Exists, Not Found, Duplicate In List or Building Not Found."""
    buildings = {normalize(b.get("name", "")) for b in client.list_buildings()}
    by_name: dict[str, list[str]] = {}
    for bname, loc in client.list_all_locations():
        by_name.setdefault(normalize(loc.get("name", "")), []).append(bname)
    seen: set[tuple[str, str]] = set()
    rows = []
    for name, building in entries:
        key = (normalize(name), normalize(building))
        shown = f"{building} / {name}" if building else name
        if key in seen:
            rows.append(_row(shown, building, "Duplicate In List", "Listed more than once."))
            continue
        seen.add(key)
        homes = by_name.get(key[0], [])
        if building:
            if key[1] not in buildings:
                rows.append(_row(shown, building, "Building Not Found", "The Building does not exist in RedSky."))
            elif any(normalize(h) == key[1] for h in homes):
                rows.append(_row(shown, building, "Exists"))
            else:
                rows.append(_row(shown, building, "Not Found"))
        elif not homes:
            rows.append(_row(shown, "", "Not Found"))
        else:
            rows.append(_row(shown, "", "Exists", ", ".join(sorted({h for h in homes if h}))))
    return rows


def ip_range(low: str, high: str) -> tuple[int, int, str]:
    """(low, high, 'low - high') of a range given as two addresses, one address or a CIDR block. Raises ValueError."""
    if not high and "/" in low:
        net = ipaddress.ip_network(low, strict=False)
        a, b = net[0], net[-1]
    else:
        a, b = ipaddress.ip_address(low), ipaddress.ip_address(high or low)
        if a.version != b.version:
            raise ValueError("The two addresses are not the same IP version.")
        if int(a) > int(b):
            raise ValueError("The low address is higher than the high address.")
    return int(a), int(b), f"{a} - {b}"


def _existing_ranges(client: RedskyClient) -> list[tuple[int, int, dict]]:
    found = []
    for r in client.list_ip_ranges():
        try:
            lo, hi, _ = ip_range(str(r.get("ipAddressLow", "")).strip(), str(r.get("ipAddressHigh", "")).strip())
        except ValueError:
            continue
        found.append((lo, hi, r))
    return found


def _location_index(client: RedskyClient) -> dict[str, tuple[str, str]]:
    """{location id: (location name, building name)}."""
    return {loc["id"]: (loc.get("name", "").strip(), (bname or "").strip())
            for bname, loc in client.list_all_locations() if loc.get("id")}


def _where(r: dict, index: dict[str, tuple[str, str]]) -> tuple[str, str]:
    """(location name, building name) of the Location an existing range is tied to ('' when RedSky gives none)."""
    for key in ("locationId", "erlId", "location"):
        value = r.get(key)
        value = value.get("id") if isinstance(value, dict) else value
        if value in index:
            return index[value]
    for key in ("locationName", "location", "erlName"):
        if isinstance(r.get(key), str) and r[key].strip():
            return r[key].strip(), ""
    return "", ""


def _span(r: dict) -> str:
    return f"{r.get('ipAddressLow', '?')} - {r.get('ipAddressHigh', '?')}"


def _join(items) -> str:
    return ", ".join(dict.fromkeys(i for i in items if i))


def precheck_ips(client: RedskyClient, entries: list[tuple[str, str]]) -> list[dict[str, str]]:
    """One result row per range: Exists (same range), Overlaps (shares addresses), Not Found, Invalid, Duplicate In List."""
    existing = _existing_ranges(client)
    index: dict[str, tuple[str, str]] | None = None
    addresses: dict[str, str] = {}
    seen: set[tuple[int, int]] = set()
    rows = []
    for low, high in entries:
        try:
            lo, hi, label = ip_range(low, high)
        except ValueError as e:
            rows.append(_row(f"{low} {high}".strip(), "", "Invalid", str(e)))
            continue
        if (lo, hi) in seen:
            rows.append(_row(label, "", "Duplicate In List", "Listed more than once."))
            continue
        seen.add((lo, hi))
        same = [r for a, b, r in existing if (a, b) == (lo, hi)]
        over = [r for a, b, r in existing if a <= hi and lo <= b and (a, b) != (lo, hi)]
        if (same or over) and index is None:
            index = _location_index(client)
            addresses = {b.get("name", "").strip(): building_address(b) for b in client.list_buildings()}
        if same or over:
            hits = same or over
            places = [_where(r, index) for r in hits]
            buildings = [bld for _loc, bld in places]
            rows.append(_row(label, _join(buildings), "Exists" if same else "Overlaps",
                             _join(loc for loc, _bld in places), _join(_span(r) for r in hits),
                             _join(addresses.get(bld, "") for bld in buildings)))
        else:
            rows.append(_row(label, "", "Not Found"))
    return rows
