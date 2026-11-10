"""RedSky audits: Find Duplicate Buildings, Remediate Duplicate Buildings, Find Buildings Without Locations and
Find Locations Without Device Tracking.

Device tracking = static MACs, LLDP (switches and ports), BSSIDs and Private IP ranges. Each is tied to a Location,
and a Location belongs to a Building, so a Building's tracking is the tracking of its Locations.

The networking list, update and delete endpoints are not in the reference JSON (webui/reference/redsky-api-docs.json);
the paths used here are guesses by analogy. Nothing was tested against a real RedSky tenant.
"""

from dataclasses import dataclass, field
from typing import Callable

from .redsky_api import RedskyClient, RedskyError
from .redsky_common import CheckSpec, normalize
from .redsky_precheck import building_address, normalize_address, same_address

KINDS = ("MAC", "LLDP", "BSSID", "Private IP")
_PATHS = {"MAC": "/networking-service/macAddress", "LLDP chassis": "/networking-service/networkSwitch",
          "LLDP port": "/networking-service/networkSwitchPort", "BSSID": "/networking-service/bssid",
          "Private IP": "/networking-service/ipRange"}
_LOC_KEYS = ("locationId", "erlId")
_LOC_OBJECTS = ("location", "erl")
COPY_FIELDS = ("info", "alternateId", "callbackNumber", "htmlLinkUrl", "htmlLinkName", "orgNameOverride")


@dataclass
class Tracked:
    kind: str  # one of KINDS
    path_kind: str  # key of _PATHS
    label: str
    raw: dict
    location_id: str


def _location_id(item: dict) -> str:
    for key in _LOC_KEYS:
        if item.get(key):
            return str(item[key])
    for key in _LOC_OBJECTS:
        value = item.get(key)
        if isinstance(value, dict) and value.get("id"):
            return str(value["id"])
    return ""


def _has_location_field(item: dict) -> bool:
    return any(k in item for k in _LOC_KEYS) or any(isinstance(item.get(k), dict) for k in _LOC_OBJECTS)


def _pick(item: dict, *keys: str) -> str:
    for key in keys:
        if item.get(key):
            return str(item[key])
    return ""


def _label(kind: str, item: dict) -> str:
    if kind == "MAC":
        return _pick(item, "macAddress", "mac", "address", "mac_address") or item.get("id", "")
    if kind == "BSSID":
        return _pick(item, "bssid") or item.get("id", "")
    if kind == "Private IP":
        return f"{item.get('ipAddressLow', '?')}-{item.get('ipAddressHigh', '?')}"
    if kind == "LLDP chassis":
        return _pick(item, "chassisId") or item.get("id", "")
    return f"{_pick(item, 'chassisId', 'networkSwitchId')} {_pick(item, 'portId')}".strip()


def collect_tracking(client: RedskyClient) -> dict[str, list[Tracked]]:
    """Every tracking record that is tied to a Location, keyed by location id. Raises RedskyError when a list cannot
    be read (a partial answer would make Locations look untracked)."""
    sources: list[tuple[str, str, str, Callable[[], list[dict]]]] = [
        ("MAC", "MAC", "static MACs", client.list_static_macs),
        ("LLDP", "LLDP chassis", "LLDP switches", client.list_network_switches),
        ("LLDP", "LLDP port", "LLDP switch ports", client.list_network_switch_ports),
        ("BSSID", "BSSID", "BSSIDs", client.list_bssids),
        ("Private IP", "Private IP", "Private IP ranges", client.list_ip_ranges),
    ]
    found: dict[str, list[Tracked]] = {}
    for kind, path_kind, title, lister in sources:
        items = lister()
        if items and not any(_has_location_field(i) for i in items):
            raise RedskyError(f"The {title} records have no recognized location field, so they cannot be tied to a "
                              f"Location. Fields on a record: {', '.join(sorted(items[0]))}.")
        for item in items:
            loc = _location_id(item)
            if loc:
                found.setdefault(loc, []).append(Tracked(kind, path_kind, _label(path_kind, item), item, loc))
    return found


def locations_of(client: RedskyClient) -> tuple[list[dict], dict[str, list[dict]]]:
    """(buildings, {building id: locations})."""
    buildings = client.list_buildings()
    return buildings, {b["id"]: client.list_locations(b["id"]) for b in buildings}


# --- duplicate buildings ---

def duplicate_groups(buildings: list[dict]) -> list[list[dict]]:
    """Groups of two or more Buildings that share an address (same_address: punctuation and street words normalized,
    a trailing city/state/zip allowed). Buildings with no address are left out. Largest groups first."""
    addressed = [(b, normalize_address(building_address(b))) for b in buildings]
    addressed = [(b, a) for b, a in addressed if a]
    parent = list(range(len(addressed)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(addressed)):
        for j in range(i + 1, len(addressed)):
            if same_address(addressed[i][1], addressed[j][1]):
                parent[find(j)] = find(i)
    groups: dict[int, list[dict]] = {}
    for i, (b, _a) in enumerate(addressed):
        groups.setdefault(find(i), []).append(b)
    found = [sorted(g, key=lambda b: normalize(b.get("name", ""))) for g in groups.values() if len(g) > 1]
    return sorted(found, key=lambda g: (-len(g), normalize(building_address(g[0]))))


def require_addresses(buildings: list[dict]) -> None:
    if buildings and not any(building_address(b) for b in buildings):
        raise RedskyError("RedSky returned no address for any Building, so duplicates cannot be found. Fields on a "
                          f"Building record: {', '.join(sorted(buildings[0]))}.")


def find_duplicates(client: RedskyClient) -> tuple[int, list[dict[str, str]], list[list[dict]]]:
    """(buildings checked, report rows, groups). One row per Building in a duplicate group."""
    buildings, locs = locations_of(client)
    require_addresses(buildings)
    groups = duplicate_groups(buildings)
    rows = []
    for n, group in enumerate(groups, 1):
        group_locations = [loc.get("name", "") for b in group for loc in locs[b["id"]]]
        for b in group:
            names = sorted((loc.get("name", "") for loc in locs[b["id"]]), key=normalize)
            row = {"group": str(n), "building": b.get("name", ""), "buildingId": b["id"],
                   "address": building_address(b), "locations": str(len(names)), "locationNames": "\n".join(names),
                   "badName": "1" if suspect_building_name(b.get("name", ""), group_locations) else ""}
            rows.append(row)
    return len(buildings), rows, groups


def suspect_building_name(building: str, location_names: list[str]) -> bool:
    """True when a Location name (of any Building in the duplicate group) is part of this Building's name, a sign
    the Building name is the correct name with a Location glued on. A Location named exactly like the Building, or
    shorter than 3 characters, does not count."""
    name = normalize(building)
    return any(len(loc) >= 3 and loc != name and loc in name for loc in (normalize(n) for n in location_names))


def duplicate_workbook(rows: list[dict[str, str]]) -> bytes:
    """The Find Duplicate Buildings report as an .xlsx. Columns: Group, Building, Correct Building Name (a TRUE/FALSE
    dropdown, FALSE by default; a group with more than one TRUE turns red), Address, Locations, then one column
    per Location name. Suspect Building names are yellow."""
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.formatting.rule import FormulaRule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    fixed = [("group", "Group"), ("building", "Building"), ("correct", "Correct Building Name"),
             ("address", "Address"), ("locations", "Locations")]
    names = [r["locationNames"].split("\n") if r["locationNames"] else [] for r in rows]
    most = max((len(n) for n in names), default=0)
    headers = [h for _k, h in fixed] + [f"Location {i}" for i in range(1, most + 1)]

    wb = Workbook()
    ws = wb.active
    ws.title = "Duplicate Buildings"
    ws.append(headers)
    for row, locs in zip(rows, names):
        ws.append([False if k == "correct" else (int(row[k]) if k in ("group", "locations") else row[k])
                   for k, _h in fixed] + locs)
    last = len(rows) + 1
    header_fill = PatternFill("solid", start_color="1F4E79")
    for cell in ws[1]:
        cell.font, cell.fill = Font(bold=True, color="FFFFFF"), header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{last}"

    building_col = 2
    yellow = PatternFill("solid", start_color="FFFF00")
    light_blue = PatternFill("solid", start_color="DDEBF7")
    white = PatternFill("solid", start_color="FFFFFF")
    thin = Side(style="thin", color="BFBFBF")
    for i, row in enumerate(rows, 2):
        band = light_blue if int(row["group"]) % 2 == 0 else white  # whole groups alternate
        for col in range(1, len(headers) + 1):
            cell = ws.cell(i, col)
            cell.fill = band
            cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
            cell.alignment = Alignment(vertical="center", horizontal="center" if col in (1, 3, 5) else "left")
        if row["badName"]:
            ws.cell(i, building_col).fill = yellow
    if rows:
        dv = DataValidation(type="list", formula1='"TRUE,FALSE"', allow_blank=False, showErrorMessage=True,
                            errorTitle="Correct Building Name", error="Choose TRUE or FALSE.")
        ws.add_data_validation(dv)
        dv.add(f"C2:C{last}")
        ws.conditional_formatting.add(f"C2:C{last}", FormulaRule(
            formula=[f"COUNTIFS($A$2:$A${last},$A2,$C$2:$C${last},TRUE)>1"],
            fill=PatternFill("solid", bgColor="FF9999", start_color="FF9999", end_color="FF9999"),
            font=Font(bold=True, color="9C0006")))
    for col in range(1, len(headers) + 1):
        width = max(len(str(c.value or "")) for c in ws[get_column_letter(col)][:200])
        ws.column_dimensions[get_column_letter(col)].width = min(max(width + 2, 10), 60)

    notes = wb.create_sheet("Notes")
    for line in ("Correct Building Name: set TRUE on the one Building to keep in each group, FALSE on the others.",
                 "A group with more than one TRUE turns red in that column.",
                 "Yellow Building name: a Location name in the group is contained in this Building's name, so it is "
                 "probably a Building name with a Location added to it."):
        notes.append([line])
    notes.column_dimensions["A"].width = 110
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


DUPLICATE_COLUMNS = (("group", "Group"), ("building", "Building"), ("address", "Address"),
                     ("locations", "Locations"))


# --- remediation ---

def option_label(b: dict) -> str:
    return f"{b.get('name', '')} ({b['id'][:8]})"


def group_options(groups: list[list[dict]], locs: dict[str, list[dict]]) -> list[dict]:
    """UI groups: id, address, option labels and the default Building to keep (most Locations, then name)."""
    out = []
    for n, g in enumerate(groups, 1):
        best = max(g, key=lambda b: len(locs[b["id"]]))
        out.append({"id": str(n), "address": building_address(g[0]), "options": [option_label(b) for b in g],
                    "ids": [b["id"] for b in g], "keep": option_label(best)})
    return out


@dataclass
class DupBuilding:
    building: dict
    locations: list[dict]


@dataclass
class Plan:
    keep: dict
    duplicates: list[DupBuilding] = field(default_factory=list)


def _target_name(name: str, dup_name: str, keep_name: str) -> str:
    """'<dup> - Entire Site' becomes '<keep> - Entire Site'; other names stay."""
    suffix = " - Entire Site"
    if normalize(name) == normalize(dup_name + suffix):
        return keep_name + suffix
    return name


def build_plans(client: RedskyClient, choices: list[tuple[str, list[str]]]) -> tuple[list[Plan], dict[str, list[dict]],
                                                                                    dict[str, list[Tracked]]]:
    """choices: (id of the Building to keep, ids of its duplicates) per group. Reads RedSky afresh."""
    buildings, locs = locations_of(client)
    by_id = {b["id"]: b for b in buildings}
    plans = []
    for keep_id, dup_ids in choices:
        if keep_id not in by_id or any(d not in by_id for d in dup_ids):
            raise RedskyError("A Building in the plan no longer exists in RedSky. Find the duplicates again.")
        plans.append(Plan(by_id[keep_id], [DupBuilding(by_id[d], locs[d]) for d in dup_ids if d != keep_id]))
    return plans, locs, collect_tracking(client)


def preview_rows(plans: list[Plan], locs: dict[str, list[dict]], tracking: dict[str, list[Tracked]]) -> list[dict[str, str]]:
    rows = []
    for plan in plans:
        keep_locs = {normalize(loc.get("name", "")) for loc in locs[plan.keep["id"]]}
        for dup in plan.duplicates:
            moved = [t for loc in dup.locations for t in tracking.get(loc["id"], [])]
            create = [loc for loc in dup.locations
                      if normalize(_target_name(loc.get("name", ""), dup.building.get("name", ""),
                                                plan.keep.get("name", ""))) not in keep_locs]
            rows.append({
                "keep": plan.keep.get("name", ""), "duplicate": dup.building.get("name", ""),
                "locations": str(len(dup.locations)), "create": str(len(create)),
                "macs": str(sum(t.kind == "MAC" for t in moved)), "lldp": str(sum(t.kind == "LLDP" for t in moved)),
                "bssids": str(sum(t.kind == "BSSID" for t in moved)),
                "ips": str(sum(t.kind == "Private IP" for t in moved))})
    return rows


PREVIEW_COLUMNS = (("keep", "Keep"), ("duplicate", "Delete"), ("locations", "Locations"),
                   ("create", "Locations To Create In Kept Building"), ("macs", "MACs"), ("lldp", "LLDP"),
                   ("bssids", "BSSID"), ("ips", "Private IP Ranges"))


def _repoint(client: RedskyClient, item: Tracked, new_location_id: str) -> None:
    raw = dict(item.raw)
    if not _has_location_field(raw):
        raise RedskyError(f"{item.kind} {item.label} has no location field to change")
    for key in _LOC_KEYS:
        if key in raw:
            raw[key] = new_location_id
    for key in _LOC_OBJECTS:
        if isinstance(raw.get(key), dict):
            raw[key] = {**raw[key], "id": new_location_id}
    client.update_tracking(_PATHS[item.path_kind], raw)


def remediation_items(client: RedskyClient, plans: list[Plan], locs: dict[str, list[dict]],
                      tracking: dict[str, list[Tracked]]) -> list[tuple[str, Callable[[], str]]]:
    """Run items in order, per duplicate Building: one per Location (find or create the matching Location in the kept
    Building, move its tracking there, delete the old Location), then one that deletes the Building. The Building is
    only deleted when every step before it worked."""
    items: list[tuple[str, Callable[[], str]]] = []
    for plan in plans:
        keep_name = plan.keep.get("name", "")
        keep_locs = {normalize(loc.get("name", "")): loc["id"] for loc in locs[plan.keep["id"]]}
        for dup in plan.duplicates:
            dup_name = dup.building.get("name", "")
            failed: list[str] = []

            for loc in dup.locations:
                def move_location(loc=loc, dup_name=dup_name, keep_name=keep_name, keep=plan.keep, keep_locs=keep_locs,
                                  failed=failed):
                    try:
                        name = _target_name(loc.get("name", ""), dup_name, keep_name)
                        target = keep_locs.get(normalize(name))
                        note = "existing"
                        if not target:
                            target, _ = client.create_location(
                                name, keep["id"], **{k: str(loc.get(k) or "") for k in COPY_FIELDS})
                            if not target:
                                raise RedskyError("RedSky did not return the id of the new Location")
                            keep_locs[normalize(name)] = target
                            note = "created"
                        moved = tracking.get(loc["id"], [])
                        for t in moved:
                            _repoint(client, t, target)
                        client.delete_location(loc["id"])
                        counts = ", ".join(f"{sum(t.kind == k for t in moved)} {k}" for k in KINDS
                                           if any(t.kind == k for t in moved)) or "no tracking"
                        return f"Moved {counts} to {note} Location '{name}' in {keep_name}, deleted the old Location"
                    except Exception:
                        failed.append(loc.get("name", ""))
                        raise
                items.append((f"{dup_name} / {loc.get('name', '')}", move_location))

            def delete_building(dup=dup, failed=failed, dup_name=dup_name):
                if failed:
                    raise RedskyError(f"Not deleted: {len(failed)} Location step(s) failed ({', '.join(failed[:3])})")
                client.delete_building(dup.building["id"])
                return f"Deleted Building {dup_name}"
            items.append((f"{dup_name} (Building)", delete_building))
    return items


# --- check tools ---

def _buildings_without_locations(client: RedskyClient) -> tuple[int, list[dict[str, str]]]:
    buildings = client.list_buildings()
    empty = [{"building": b.get("name", ""), "buildingId": b["id"], "address": building_address(b)}
             for b in buildings if not client.list_locations(b["id"])]
    return len(buildings), empty


NO_LOCATIONS = CheckSpec(
    slug="no-locations", title="Find Buildings Without Locations", noun="building",
    blurb="List every Building that has no Locations under it.",
    columns=(("building", "Building"), ("address", "Address"), ("buildingId", "Building ID")),
    run=_buildings_without_locations,
    ok_message="Every building has at least one location.",
)


def _locations_without_tracking(client: RedskyClient, text: str = "") -> tuple[int, list[dict[str, str]]]:
    """Locations are read per Building so each knows its Building and address. A Location the organization-level list
    returns that is not under any Building (matched by id) is reported with a blank Building."""
    tracking = collect_tracking(client)
    seen: set[str] = set()
    entries: list[tuple[str, str, dict]] = []
    for b in client.list_buildings():
        for loc in client.list_locations(b["id"]):
            if loc["id"] not in seen:
                seen.add(loc["id"])
                entries.append((b.get("name", ""), building_address(b), loc))
    for loc in client.list_locations():
        if loc["id"] not in seen:
            seen.add(loc["id"])
            entries.append(("", building_address(loc), loc))
    text = text.strip().lower()
    if text:  # only Locations whose name contains the text are checked and reported
        entries = [e for e in entries if text in e[2].get("name", "").lower()]
    missing = [{"building": name, "address": address, "location": loc.get("name", "")}
               for name, address, loc in entries if loc["id"] not in tracking]
    return len(entries), missing


NO_TRACKING = CheckSpec(
    slug="no-tracking", title="Find Locations Without Device Tracking", noun="location",
    blurb="List every Location that has no device tracking: no static MAC, LLDP switch or port, BSSID or Private IP "
          "range is tied to it. Enter text to check only Locations whose name contains it. The check stops with an error if any of the four lists cannot be read.",
    columns=(("building", "Building"), ("address", "Building Address"), ("location", "Location")),
    run=_locations_without_tracking,
    ok_message="Every location has device tracking.",
    input_label="Location Name Contains",
    input_optional=True,
    input_hint="Optional. Only Locations whose name contains this text (any case) are checked and reported. "
               "Leave empty to check every Location.",
    input_placeholder="Floor 2",
)


def _primary_location_exists(client: RedskyClient, pattern: str) -> tuple[int, list[dict[str, str]]]:
    """Buildings with no Location named like `pattern`; {building} stands for the Building's name."""
    pattern = pattern.strip()
    if not pattern:
        raise RedskyError("Enter the primary Location name to look for.")
    buildings = client.list_buildings()
    missing = []
    for b in buildings:
        name = b.get("name", "").strip()
        expected = pattern.replace("{building}", name)
        if not any(normalize(loc.get("name", "")) == normalize(expected) for loc in client.list_locations(b["id"])):
            missing.append({"building": name, "address": building_address(b), "expectedLocation": expected})
    return len(buildings), missing


PRIMARY_LOCATION = CheckSpec(
    slug="primary-location", title="Check Primary Location Exists", noun="building",
    blurb="Check that every Building has a primary Location with the name you enter. Write {building} where the "
          "Building's name belongs. The name is matched case-insensitively, ignoring extra spaces.",
    columns=(("building", "Building"), ("address", "Building Address"), ("expectedLocation", "Expected Location")),
    run=_primary_location_exists,
    ok_message="Every building has the primary location.",
    input_label="Primary Location Name",
    input_hint="Use {building} for the Building's name, for example: {building} - Main. Without {building} the text is "
               "used as written for every Building.",
    input_placeholder="{building} - ",
)
