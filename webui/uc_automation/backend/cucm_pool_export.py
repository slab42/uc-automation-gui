"""CUCM Device Export for Webex: phones in chosen device pools with owner, lines and BLFs, as an Excel workbook.

Device names come from SQL, the rest of each phone from AXL getPhone (a few threads), end users from SQL.
The owner of a device is found in this order: the device Owner User ID, the end user's associated devices,
then the line (associated end users of a line, or an end user whose primary extension is that line).
When none is found, the phone description, then the line 1 description, then the line 1 display name are
matched against user IDs and first/last name combinations. A guess is marked in Owner Source and highlighted.
"""

import calendar
import re

from datetime import date, datetime

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from .cucm_axl import AxlError, _call, _text, list_paged, sql_quote, sql_rows
from .cucm_connections import CucmConnection
from .cucm_reports import registered_names

WORKERS = 4
LINE_FIELDS = ["DN", "Partition", "Description", "Display", "Label", "External Mask", "Caller ID"]
PHONE_COLUMNS = ["Webex Location", "Type", "Device Name", "Device Type", "Device Pool", "Description",
                 "Phone Template", "Registration Status", "Last Registered", "User ID", "First Name", "Last Name", "Email",
                 "Owner Source", "Notes"]
# Excel Output Options: option label -> (phone columns, line fields). Unchecked options are hidden columns.
EXCEL_OPTIONS = {
    "Device Pool Name": (["Device Pool"], []),
    "First Name": (["First Name"], []), "Last Name": (["Last Name"], []), "Owner Source": (["Owner Source"], []),
    "Phone Template": (["Phone Template"], []), "Line Partitions": ([], ["Partition"]),
    "Line Descriptions": ([], ["Description"]), "Line Displays": ([], ["Display"]), "Line Labels": ([], ["Label"]),
    "Line External Masks": ([], ["External Mask"]), "Line Caller ID": ([], ["Caller ID"]),
}
# Phone fields the Webex Location can be taken from
LOCATION_FIELDS = ["Device Pool", "Device Name", "Description", "Phone Template", "Device Type", "User ID", "Email"]
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
    """Device pool names containing `search` (case-insensitive), sorted. `|` separates alternatives:
    "Phone|711" finds names containing Phone or 711. A blank search lists all."""
    terms = [t.strip().lower() for t in search.split("|") if t.strip()]
    names = [p["name"] for p in list_paged(conn, "listDevicePool", "devicePool", {"name": "%"}, ["name"])]
    return sorted((n for n in names if not terms or any(t in n.lower() for t in terms)), key=str.lower)


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
    try:
        rows = list_paged(conn, "listUser", "user", {"userid": "%"},
                          ["userid", "firstName", "lastName", "mailid", "directoryUri"])
    except AxlError:   # older CUCM without Directory URI
        rows = list_paged(conn, "listUser", "user", {"userid": "%"}, ["userid", "firstName", "lastName", "mailid"])
    users = {r["userid"].strip().lower(): {"userid": r["userid"], "firstname": r.get("firstName", ""),
                                   "lastname": r.get("lastName", ""), "mailid": r.get("mailid", ""),
                                   "directoryuri": r.get("directoryUri", "")} for r in rows if r.get("userid")}
    dev: dict[str, list[str]] = {}
    try:
        for r in sql_rows(conn, "select d.name as device, e.userid as userid from enduserdevicemap m "
                                "join device d on d.pkid = m.fkdevice join enduser e on e.pkid = m.fkenduser", 2):
            dev.setdefault(r["device"].upper(), []).append(r["userid"])
    except AxlError:
        pass
    ext: dict[tuple[str, str], list[str]] = {}
    try:   # primary extension: a failure here must not lose names and emails
        from zeep.helpers import serialize_object
        skip = 0
        while True:
            resp = _call(conn, "listUser", searchCriteria={"userid": "%"},
                         returnedTags={"userid": "", "primaryExtension": {"pattern": "", "routePartitionName": ""}},
                         skip=skip, first=500)
            data = serialize_object(resp["return"]) if resp["return"] is not None else {}
            batch = (data or {}).get("user") or []
            for u in batch:
                pe = u.get("primaryExtension") or {}
                if u.get("userid") and pe.get("pattern"):
                    part = pe.get("routePartitionName")
                    part = part.get("_value_1", "") if isinstance(part, dict) else (part or "")
                    ext.setdefault((pe["pattern"], part), []).append(u["userid"])
            if len(batch) < 500:
                break
            skip += 500
    except AxlError:
        pass
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

    last_seen: dict[str, date] = {}
    seen_ok = False
    if registration and devices:   # registrationdynamic keeps the last time (epoch seconds) each device was seen
        try:
            for r in sql_rows(conn, (
                    "select d.name as name, rd.lastseen as seen, rd.lastactive as active from registrationdynamic rd "
                    "join device d on d.pkid = rd.fkdevice join devicepool dp on dp.pkid = d.fkdevicepool "
                    f"where dp.name in ({quoted})"), 3):
                stamp = max((int(v) for v in (r["seen"], r["active"]) if v.strip().isdigit()), default=0)
                if stamp > 0:
                    last_seen[r["name"].upper()] = datetime.fromtimestamp(stamp).date()
            seen_ok = True
        except AxlError as e:
            errors.append({"Device Name": "", "Error": f"Last registered lookup failed: {e}"})

    def last_registered(name: str) -> str:
        """ISO date, "Never" (lookup worked, never seen, not registered) or blank (unknown)."""
        if not registration:
            return ""
        if name.upper() in reg:
            return str(date.today())
        if name.upper() in last_seen:
            return str(last_seen[name.upper()])
        return "Never" if seen_ok and reg_complete else ""

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
        for ln in p["lines"]:
            ln["Description"] = dn_desc.get((ln["DN"], ln["Partition"]), "")
        if not ids and users:
            line1 = next((ln for ln in p["lines"] if ln["index"] == 1), p["lines"][0] if p["lines"] else {})
            uid, source = guess_user([("Phone Description", p["description"]),
                                      ("Line 1 Description", line1.get("Description", "")),
                                      ("Line 1 Display", line1.get("Display", ""))], users)
            ids, guessed = ([uid], True) if uid else ([], False)
        u = users.get(ids[0].strip().lower(), {}) if ids else {}
        phones.append({
            "Type": "User" if ids else "Workspace", "Device Name": name,
            "Device Type": d["model"], "Device Pool": d["pool"], "Description": p["description"],
            "Phone Template": p["template"],
            "Registration Status": reg_status(name),
            "Last Registered": last_registered(name),
            "User ID": ids[0] if ids else "", "First Name": u.get("firstname", ""), "Last Name": u.get("lastname", ""),
            "Email": _email(u), "Owner Source": source, "guessed": guessed,
            "Notes": f"Other users: {', '.join(ids[1:])}" if len(ids) > 1 else "",
            "lines": p["lines"],
        })
        max_lines = max(max_lines, max((ln["index"] for ln in p["lines"]), default=0))
        blfs.extend({"Device Name": name, "BLF Index": b["index"], "Destination": b["dest"], "Label": b["label"]}
                    for b in p["blfs"])
    return {"phones": phones, "blfs": blfs, "errors": errors, "max_lines": max_lines, "reg_complete": reg_complete}


def _replacement(text: str) -> str:
    """Python replacement template: $1 is accepted as well as \\1."""
    return re.sub(r"\$(\d+)", r"\\g<\1>", text)


def check_location_regex(pattern: str, replace: str | None = None) -> str:
    """"" when `pattern` (and the replacement, when given) is usable, else the error text."""
    try:
        rx = re.compile(pattern)
        if replace is not None and pattern:
            rx.sub(_replacement(replace), "")
            # a group reference that does not exist only fails when the pattern matches, so test an empty match too
            for m in [rx.search(s) for s in ("", "a", "a-b", "1")]:
                if m:
                    m.expand(_replacement(replace))
    except (re.error, IndexError) as e:
        return f"Invalid regular expression: {e}"
    return ""


def derive_location(phone: dict, field: str, pattern: str, replace: str | None = None) -> str:
    """Webex Location of a phone: the value of `field`, narrowed by the regex `pattern` (blank = whole value).
    Extract mode (`replace` is None): with a match the first capture group is used if the pattern has one, else
    the whole match; no match gives "". Replace mode: every match is replaced by `replace` (\\1 or $1 for groups)
    and the rest of the value is kept."""
    value = str(phone.get(field, "") or "")
    if not pattern:
        return value
    try:
        if replace is not None:
            return re.sub(pattern, _replacement(replace), value)
        m = re.search(pattern, value)
    except (re.error, IndexError):
        return ""
    if not m:
        return ""
    return (m.group(1) if m.re.groups else m.group(0)) or ""


def phone_headers(max_lines: int, registration: bool = True) -> list[str]:
    """Phone sheet headers. Registration Status and Last Registered are dropped when `registration` is False."""
    cols = [c for c in PHONE_COLUMNS if registration or c not in ("Registration Status", "Last Registered")]
    return cols + [f"Line {n} {f}" for n in range(1, max_lines + 1) for f in LINE_FIELDS]


def hidden_headers(headers: list[str], options: set[str] | None) -> set[str]:
    """Headers to hide: the columns of every EXCEL_OPTIONS entry that is not in `options` (None = none hidden)."""
    if options is None:
        return set()
    hide: set[str] = set()
    for label, (cols, fields) in EXCEL_OPTIONS.items():
        if label not in options:
            hide.update(cols)
            hide.update(h for h in headers if h.startswith("Line ") and h.split(" ", 2)[2] in fields)
    return hide


def phone_row(phone: dict, max_lines: int) -> dict[str, str]:
    """A phone as one flat row: PHONE_COLUMNS plus `Line N <field>` columns keyed by the line index."""
    row = {c: phone.get(c, "") for c in PHONE_COLUMNS}
    for ln in phone["lines"]:
        if 1 <= ln["index"] <= max_lines:
            for f in LINE_FIELDS:
                row[f"Line {ln['index']} {f}"] = ln[f]
    return row


def build_workbook(result: dict, extra_sheets: list[tuple[str, list[str], list[dict]]] | None = None,
                   options: set[str] | None = None, registration: bool = True,
                   location_field: str = "Device Pool", location_regex: str = "",
                   location_replace: str | None = None, bad_emails: set[str] | None = None,
                   supported_models: set[str] | None = None) -> bytes:
    """The export workbook (xlsx bytes). `extra_sheets` is [(name, headers, rows)] for later additions
    such as a Hunt Groups sheet. `bad_emails` (lower case) are the addresses Webex does not know: their Email cells
    get Excel's Bad colors, and so do blank Email cells of rows that have a User ID (only when `bad_emails` is
    given, even if empty). `supported_models` (lower case model codes and display names Webex supports, from
    get_supported_devices): Device Type cells not in it get the Bad colors (only when given)."""
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    phones = sorted(({**p, "Webex Location": derive_location(p, location_field, location_regex, location_replace)}
                     for p in result["phones"]), key=lambda p: p["Device Name"].lower())
    # second sort (stable, so equal User IDs stay in Device Name order); blank User IDs go last like Excel does
    phones.sort(key=lambda p: (not p["User ID"].strip(), p["User ID"].strip().lower()))
    max_lines = result["max_lines"]
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
    headers = phone_headers(max_lines, registration)
    sheet("Phones", "Phones", headers, [phone_row(p, max_lines) for p in phones])
    hidden = hidden_headers(headers, options)
    for i, h in enumerate(headers, 1):
        if h in hidden:
            wb["Phones"].column_dimensions[get_column_letter(i)].hidden = True
    notes: dict[str, list[str]] = {}   # header -> what its highlighting means, shown as a header comment

    def note(header: str, text: str) -> None:
        if header in headers:
            notes.setdefault(header, []).append(text)

    yellow = PatternFill("solid", fgColor="FFFF00")
    cols = [headers.index(c) + 1 for c in ("User ID", "First Name", "Last Name") if c in headers]
    guessed_any = False
    for i, p in enumerate(phones, 2):
        if p.get("guessed"):
            guessed_any = True
            for c in cols:
                wb["Phones"].cell(row=i, column=c).fill = yellow
    if guessed_any:
        for h in ("User ID", "First Name", "Last Name"):
            note(h, "Yellow: the user was guessed from the phone description or line text (see Owner Source), not found as an owner or associated user.")
    if phones:   # Type only accepts User or Workspace
        from openpyxl.worksheet.datavalidation import DataValidation
        tcol = get_column_letter(headers.index("Type") + 1)
        dv = DataValidation(type="list", formula1='"User,Workspace"', allow_blank=False, showErrorMessage=True,
                            errorTitle="Invalid Type", error="Type must be User or Workspace.")
        dv.add(f"{tcol}2:{tcol}{len(phones) + 1}")
        wb["Phones"].add_data_validation(dv)
    if registration and "Last Registered" in headers:   # last registered more than 3 months ago or never: Bad on the device name
        today = date.today()
        m = today.year * 12 + today.month - 1 - 3
        cutoff = date(m // 12, m % 12 + 1, min(today.day, calendar.monthrange(m // 12, m % 12 + 1)[1]))
        bad_fill, bad_font = PatternFill("solid", fgColor="FFC7CE"), Font(color="9C0006")
        ncol = headers.index("Device Name") + 1
        for i, p in enumerate(phones, 2):
            last = p["Last Registered"]
            if last == "Never" or (last and date.fromisoformat(last) < cutoff):
                note("Device Name", "Red: this phone last registered more than 3 months ago, or never.")
                cell = wb["Phones"].cell(row=i, column=ncol)
                cell.fill, cell.font = bad_fill, bad_font
    if bad_emails is not None and "Email" in headers:   # Excel's Bad style
        bad_fill, bad_font = PatternFill("solid", fgColor="FFC7CE"), Font(color="9C0006")
        ecol = headers.index("Email") + 1
        for i, p in enumerate(phones, 2):
            email = p["Email"].strip().lower()
            if email in bad_emails or (not email and p["User ID"].strip()):
                note("Email", "Red: this email address was not found in Webex, or the phone has a User ID but no email.")
                cell = wb["Phones"].cell(row=i, column=ecol)
                cell.fill, cell.font = bad_fill, bad_font
    if supported_models is not None and "Device Type" in headers:   # phone models Webex does not support: Bad style
        bad_fill, bad_font = PatternFill("solid", fgColor="FFC7CE"), Font(color="9C0006")
        dcol = headers.index("Device Type") + 1
        for i, p in enumerate(phones, 2):
            if p["Device Type"].strip().lower() not in supported_models:
                note("Device Type", "Red: this phone model is not in the list of devices supported by Webex Calling.")
                cell = wb["Phones"].cell(row=i, column=dcol)
                cell.fill, cell.font = bad_fill, bad_font
    if phones:   # highlight duplicate (non-blank) user IDs with Excel's Neutral colors
        from openpyxl.formatting.rule import FormulaRule
        col = get_column_letter(headers.index("User ID") + 1)
        last = len(phones) + 1
        wb["Phones"].conditional_formatting.add(
            f"{col}2:{col}{last}",
            FormulaRule(formula=[f'AND({col}2<>"",COUNTIF(${col}$2:${col}${last},{col}2)>1)'],
                        fill=PatternFill("solid", bgColor="FFEB9C", fgColor="FFEB9C"), font=Font(color="9C5700")))
    if phones:
        seen_ids = [p["User ID"].strip().lower() for p in phones if p["User ID"].strip()]
        if len(seen_ids) != len(set(seen_ids)):
            note("User ID", "Orange: this User ID appears on more than one phone.")
    from openpyxl.comments import Comment
    for h, texts in notes.items():
        c = Comment("\n".join(dict.fromkeys(texts)), "UC Automations")
        c.width, c.height = 280, 40 + 30 * len(texts)
        wb["Phones"].cell(row=1, column=headers.index(h) + 1).comment = c
    sheet("BLFs", "BLFs", BLF_COLUMNS, result["blfs"])
    sheet("Summary", "Summary", ["Device Pool", "Phones", "Users", "Workspaces"], summary)
    sheet("Errors", "Errors", ["Device Name", "Error"], result["errors"])
    for name, hdrs, rows in extra_sheets or []:
        sheet(name, name.replace(" ", ""), hdrs, rows)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def missing_in_webex(client, emails: list[str], note: Callable[[str], None] | None = None) -> tuple[set[str], list[str]]:
    """Check each distinct email against Webex people. Returns (lower case emails Webex has no user for, failure texts)."""
    from .webex_api import WebexError

    todo = sorted({e.strip().lower() for e in emails if e.strip()})
    missing: set[str] = set()
    failed: list[str] = []

    def check(email: str) -> None:
        try:
            found = client.call("GET", "/people", {"email": email}).get("items") or []
        except WebexError as e:
            failed.append(f"{email}: {e}")
            return
        if not found:
            missing.add(email)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for n, _ in enumerate(pool.map(check, todo), 1):
            if note and (n % 25 == 0 or n == len(todo)):
                note(f"Checked {n} of {len(todo)} email addresses in Webex")
    return missing, failed
