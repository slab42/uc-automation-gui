"""CUCM Device Export for Webex: phones in chosen device pools with owner, lines and BLFs, as an Excel workbook.

Device names come from SQL, the rest of each phone from AXL getPhone (a few threads), end users from SQL.
The owner of a device is found in this order: the device Owner User ID, the end user's associated devices,
then the line (associated end users of a line, or an end user whose primary extension is that line).
When none is found, the phone description, then the line 1 description, then the line 1 display name are
matched against user IDs and first/last name combinations. A guess is marked in Owner Source and highlighted.
"""

import re

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from .cucm_axl import AxlError, _call, _text, list_paged, sql_quote, sql_rows
from .cucm_connections import CucmConnection
from .cucm_reports import registered_names

WORKERS = 4
LINE_FIELDS = ["DN", "Partition", "Display", "Label", "External Mask", "Caller ID"]
PHONE_COLUMNS = ["Type", "Device Name", "MAC", "Device Type", "Protocol", "Device Pool", "Description",
                 "Phone Template", "Registration Status", "User ID", "First Name", "Last Name", "Email",
                 "Owner Source", "Notes"]
BLF_COLUMNS = ["Device Name", "BLF Index", "Destination", "Label"]
_TAGS = {
    "name": "", "description": "", "product": "", "model": "", "protocol": "", "devicePoolName": "",
    "phoneTemplateName": "", "ownerUserName": "",
    "lines": {"line": {"index": "", "label": "", "display": "", "displayAscii": "", "e164Mask": "",
                       "dirn": {"pattern": "", "routePartitionName": ""},
                       "associatedEndusers": {"enduser": {"userId": ""}}}},
    "busyLampFields": {"busyLampField": {"blfDest": "", "label": ""}},
}


def list_pools(conn: CucmConnection, search: str = "") -> list[str]:
    """Device pool names containing `search` (case-insensitive), sorted."""
    q = search.strip().lower()
    names = [p["name"] for p in list_paged(conn, "listDevicePool", "devicePool", {"name": "%"}, ["name"])]
    return sorted((n for n in names if q in n.lower()), key=str.lower)


def _aslist(v) -> list:
    return [] if v is None else v if isinstance(v, list) else [v]


def parse_phone(data: dict) -> dict:
    """Flatten a serialized getPhone result into plain strings, lines and BLFs."""
    lines = []
    for ln in _aslist((data.get("lines") or {}).get("line")):
        dirn = ln.get("dirn") or {}
        users = [_text(u.get("userId")) for u in _aslist((ln.get("associatedEndusers") or {}).get("enduser"))]
        lines.append({
            "index": int(_text(ln.get("index")) or 0), "DN": _text(dirn.get("pattern")),
            "Partition": _text(dirn.get("routePartitionName")),
            "Display": _text(ln.get("display")), "Description": "",
            "Label": _text(ln.get("label")), "External Mask": _text(ln.get("e164Mask")),
            "Caller ID": _text(ln.get("displayAscii")), "users": [u for u in users if u],
        })
    lines.sort(key=lambda x: x["index"])
    blfs = [{"index": i, "dest": _text(b.get("blfDest")), "label": _text(b.get("label"))}
            for i, b in enumerate(_aslist((data.get("busyLampFields") or {}).get("busyLampField")), 1)]
    return {"description": _text(data.get("description")), "protocol": _text(data.get("protocol")),
            "template": _text(data.get("phoneTemplateName")), "owner": _text(data.get("ownerUserName")),
            "lines": lines, "blfs": blfs}


def _get_phone(conn: CucmConnection, name: str) -> dict:
    from zeep.helpers import serialize_object
    resp = _call(conn, "getPhone", name=name, returnedTags=_TAGS)
    data = serialize_object(resp["return"]) or {}
    return parse_phone(data.get("phone") or {})


def resolve_owner(phone: dict, device_users: dict[str, list[str]], primary_ext: dict[tuple[str, str], list[str]],
                  name: str) -> tuple[list[str], str]:
    """(user ids, source) for one phone. Source is "Device Owner", "Associated Device", "Line" or ""."""
    if phone["owner"]:
        return [phone["owner"]], "Device Owner"
    assoc = device_users.get(name.upper(), [])
    if assoc:
        return assoc, "Associated Device"
    found: list[str] = []
    for ln in phone["lines"]:
        for u in ln["users"] + primary_ext.get((ln["DN"], ln["Partition"]), []):
            if u not in found:
                found.append(u)
    return (found, "Line") if found else ([], "")


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _has_seq(words: list[str], seq: list[str]) -> bool:
    n = len(seq)
    return n > 0 and any(words[i:i + n] == seq for i in range(len(words) - n + 1))


def guess_user(texts: list[tuple[str, str]], users: dict[str, dict]) -> tuple[str, str]:
    """(user id, source label) from the first text that matches exactly one end user, else ("", "").

    `texts` is [(label, text)] in priority order. A user matches when a word equals the user ID or the text
    holds "first last" or "last first" as consecutive words."""
    for label, text in texts:
        words = _words(text)
        if not words:
            continue
        hits: list[str] = []
        for key, u in users.items():
            first, last = _words(u.get("firstname", "")), _words(u.get("lastname", ""))
            uid = u.get("userid", key)
            if (len(uid) >= 3 and uid.lower() in words) or (
                    first and last and (_has_seq(words, first + last) or _has_seq(words, last + first))):
                hits.append(uid)
        if len(hits) == 1:
            return hits[0], f"Guess: {label}"
    return "", ""


def _load_dn_descriptions(conn: CucmConnection) -> dict[tuple[str, str], str]:
    """(DN, partition) -> directory number description. getPhone does not return it."""
    return {(r["dn"], r["part"]): r["descr"] for r in sql_rows(
        conn, "select n.dnorpattern as dn, rp.name as part, n.description as descr from numplan n "
              "left join routepartition rp on rp.pkid = n.fkroutepartition where n.tkpatternusage = 2", 3)}


def _load_users(conn: CucmConnection):
    """(users by lower-case id, device name -> user ids, (DN, partition) -> user ids by primary extension)."""
    users = {r["userid"].lower(): r for r in sql_rows(
        conn, "select userid, firstname, lastname, mailid, directoryuri from enduser", 5)}
    dev: dict[str, list[str]] = {}
    for r in sql_rows(conn, "select d.name as device, e.userid as userid from enduserdevicemap m "
                            "join device d on d.pkid = m.fkdevice join enduser e on e.pkid = m.fkenduser", 2):
        dev.setdefault(r["device"].upper(), []).append(r["userid"])
    ext: dict[tuple[str, str], list[str]] = {}
    for r in sql_rows(conn, "select e.userid as userid, n.dnorpattern as dn, rp.name as part from enduser e "
                            "join numplan n on n.pkid = e.fknumplan_primary "
                            "left join routepartition rp on rp.pkid = n.fkroutepartition", 3):
        ext.setdefault((r["dn"], r["part"]), []).append(r["userid"])
    return users, dev, ext


def _email(user: dict) -> str:
    """Full email address of an end user. CUCM Mail ID is often only the part before the @, so take the
    first of Mail ID or Directory URI that holds an @."""
    return next((v for v in (user.get("mailid", ""), user.get("directoryuri", "")) if "@" in v), "")


def pool_export(conn: CucmConnection, pools: list[str], registration: bool = False,
                progress: Callable[[str], None] | None = None) -> dict:
    """Collect everything for the phones in `pools`.

    Returns {"phones": [...], "blfs": [...], "errors": [...], "max_lines": int, "reg_complete": bool}.
    A phone row holds the PHONE_COLUMNS plus "lines" (list of dicts). Failures are collected in errors."""
    note = progress or (lambda m: None)
    quoted = ", ".join(f"'{sql_quote(p)}'" for p in pools)
    devices = sql_rows(conn, (
        "select d.name as name, dp.name as pool, tm.name as model from device d "
        "join devicepool dp on dp.pkid = d.fkdevicepool join typeclass tc on tc.enum = d.tkclass "
        f"join typemodel tm on tm.enum = d.tkmodel where tc.name = 'Phone' and dp.name in ({quoted}) "
        "order by dp.name, d.name"), 3)
    note(f"{len(devices)} phone(s) found, reading end users")
    errors: list[dict[str, str]] = []
    try:
        users, dev_users, primary_ext = _load_users(conn)
    except AxlError as e:
        users, dev_users, primary_ext = {}, {}, {}
        errors.append({"Device Name": "", "Error": f"End user lookup failed: {e}"})

    try:
        dn_desc = _load_dn_descriptions(conn)
    except AxlError as e:
        dn_desc = {}
        errors.append({"Device Name": "", "Error": f"Line description lookup failed: {e}"})

    done = {"n": 0}

    def work(d: dict) -> tuple[dict, dict | None, str]:
        try:
            p = _get_phone(conn, d["name"])
            err = ""
        except AxlError as e:
            p, err = None, str(e)
        done["n"] += 1
        if done["n"] % 25 == 0 or done["n"] == len(devices):
            note(f"Read {done['n']} of {len(devices)} phones")
        return d, p, err

    with ThreadPoolExecutor(WORKERS) as ex:
        results = list(ex.map(work, devices))

    reg: set[str] = set()
    reg_complete = True
    if registration and devices:
        reg, reg_complete = registered_names(conn, [d["name"] for d in devices], "Phone", progress)

    def reg_status(name: str) -> str:
        if not registration:
            return ""
        return "Registered" if name.upper() in reg else "Unregistered" if reg_complete else ""

    phones, blfs, max_lines = [], [], 0
    for d, p, err in results:
        name = d["name"]
        if p is None:
            errors.append({"Device Name": name, "Error": err})
            p = {"description": "", "protocol": "", "template": "", "owner": "", "lines": [], "blfs": []}
        ids, source = resolve_owner(p, dev_users, primary_ext, name)
        guessed = False
        if not ids and users:
            for ln in p["lines"]:
                ln["Description"] = dn_desc.get((ln["DN"], ln["Partition"]), "")
            line1 = next((ln for ln in p["lines"] if ln["index"] == 1), p["lines"][0] if p["lines"] else {})
            uid, source = guess_user([("Phone Description", p["description"]),
                                      ("Line 1 Description", line1.get("Description", "")),
                                      ("Line 1 Display", line1.get("Display", ""))], users)
            ids, guessed = ([uid], True) if uid else ([], False)
        u = users.get(ids[0].lower(), {}) if ids else {}
        phones.append({
            "Type": "User" if ids else "Workspace", "Device Name": name,
            "MAC": name[3:] if name.upper().startswith("SEP") else "", "Device Type": d["model"],
            "Protocol": p["protocol"], "Device Pool": d["pool"], "Description": p["description"],
            "Phone Template": p["template"],
            "Registration Status": reg_status(name),
            "User ID": ids[0] if ids else "", "First Name": u.get("firstname", ""), "Last Name": u.get("lastname", ""),
            "Email": _email(u), "Owner Source": source, "guessed": guessed,
            "Notes": f"Other users: {', '.join(ids[1:])}" if len(ids) > 1 else "",
            "lines": p["lines"],
        })
        max_lines = max(max_lines, max((ln["index"] for ln in p["lines"]), default=0))
        blfs.extend({"Device Name": name, "BLF Index": b["index"], "Destination": b["dest"], "Label": b["label"]}
                    for b in p["blfs"])
    return {"phones": phones, "blfs": blfs, "errors": errors, "max_lines": max_lines, "reg_complete": reg_complete}


def phone_headers(max_lines: int) -> list[str]:
    return PHONE_COLUMNS + [f"Line {n} {f}" for n in range(1, max_lines + 1) for f in LINE_FIELDS]


def phone_row(phone: dict, max_lines: int) -> dict[str, str]:
    """A phone as one flat row: PHONE_COLUMNS plus `Line N <field>` columns keyed by the line index."""
    row = {c: phone.get(c, "") for c in PHONE_COLUMNS}
    for ln in phone["lines"]:
        if 1 <= ln["index"] <= max_lines:
            for f in LINE_FIELDS:
                row[f"Line {ln['index']} {f}"] = ln[f]
    return row


def build_workbook(result: dict, extra_sheets: list[tuple[str, list[str], list[dict]]] | None = None) -> bytes:
    """The export workbook (xlsx bytes). `extra_sheets` is [(name, headers, rows)] for later additions
    such as a Hunt Groups sheet."""
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    phones, max_lines = result["phones"], result["max_lines"]
    wb = Workbook()
    wb.remove(wb.active)

    def sheet(name, table_name, headers, rows):
        ws = wb.create_sheet(name)
        ws.append(headers)
        for r in rows:
            ws.append([r.get(h, "") for h in headers])
        for cell in ws[1]:
            cell.fill, cell.font = header_fill, header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.freeze_panes = "A2"
        if rows:
            t = Table(displayName=table_name, ref=ws.dimensions)
            t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
            ws.add_table(t)
        for i, h in enumerate(headers, 1):
            width = max([len(str(h))] + [len(str(r.get(h, ""))) for r in rows[:500]])
            ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 12), 60)

    pools: dict[str, dict[str, int]] = {}
    for p in phones:
        c = pools.setdefault(p["Device Pool"], {"User": 0, "Workspace": 0})
        c[p["Type"]] += 1
    summary = [{"Device Pool": k, "Phones": v["User"] + v["Workspace"], "Users": v["User"], "Workspaces": v["Workspace"]}
               for k, v in sorted(pools.items(), key=lambda kv: kv[0].lower())]
    headers = phone_headers(max_lines)
    sheet("Phones", "Phones", headers, [phone_row(p, max_lines) for p in phones])
    yellow = PatternFill("solid", fgColor="FFFF00")
    cols = [headers.index(c) + 1 for c in ("User ID", "First Name", "Last Name", "Email")]
    for i, p in enumerate(phones, 2):
        if p.get("guessed"):
            for c in cols:
                wb["Phones"].cell(row=i, column=c).fill = yellow
    sheet("BLFs", "BLFs", BLF_COLUMNS, result["blfs"])
    sheet("Summary", "Summary", ["Device Pool", "Phones", "Users", "Workspaces"], summary)
    sheet("Errors", "Errors", ["Device Name", "Error"], result["errors"])
    for name, hdrs, rows in extra_sheets or []:
        sheet(name, name.replace(" ", ""), hdrs, rows)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
