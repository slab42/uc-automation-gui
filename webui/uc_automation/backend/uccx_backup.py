"""Download everything it can from a UCCX server into the stored download folder (see uccx_store).

Port of backup.py from the old uccxTools scripts (reference only). Same folder layout, so the old upload scripts and
this app's upload (uccx_restore) read the same files. Each area is a function `area(client, dest, log) -> detail`
that raises UccxError when it saved nothing or something failed. No Reflex imports.
"""

from pathlib import Path
from urllib.parse import quote

from lxml import etree

from .applog import OpLog
from .uccx_api import UccxClient, UccxError, admin_path, local_name

# (API path, file name under xml/) in the order the old script saved them
SETTINGS = [
    ("skill", "skills"), ("csq", "csqs"), ("resource", "resources"), ("calendar", "calendars"), ("team", "teams"),
    ("resourceGroup", "resourceGroups"), ("application", "applications"), ("callControlGroup", "ccgs"),
    ("trigger", "triggers"), ("httpTrigger", "httpTriggers"),
]


def _write(root, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(etree.tostring(root, encoding="unicode", pretty_print=True), encoding="utf-8")


def _outcome(what: str, saved: int, failed: list[str], log: OpLog) -> str:
    """Detail text for a finished area. Anything that failed makes the area fail (the log has each reason)."""
    if failed:
        log.error(f"{what}: {len(failed)} failed: {', '.join(failed[:10])}")
        raise UccxError(f"{saved} saved, {len(failed)} failed ({', '.join(failed[:5])}{'...' if len(failed) > 5 else ''}). "
                        "See the log.")
    return f"{saved} saved"


def _good_name(name: str | None) -> bool:
    """A folder or file name from the server that is safe to use as one path part."""
    return bool(name) and name not in (".", "..") and "/" not in name and "\\" not in name


def _self_urls(path: Path) -> list[str]:
    root = etree.parse(str(path)).getroot()
    return [s.attrib.get("href") or (s.text or "") for s in root.iter("self")]


def _need(dest: Path, name: str) -> Path:
    path = dest / "xml" / name
    if not path.is_file():
        raise UccxError(f"{name} was not saved. Run Admin Settings first.")
    return path


def settings(client: UccxClient, dest: Path, log: OpLog) -> str:
    saved, failed = 0, []
    for api, name in SETTINGS:
        try:
            _write(client.admin_xml(api), dest / "xml" / f"{name}.xml")
            log.info(f"Saved {api} settings")
            saved += 1
        except UccxError as e:
            log.error(f"{api}: {e}")
            failed.append(api)
    return _outcome("Admin settings", saved, failed, log)


def _details(client: UccxClient, dest: Path, log: OpLog, source: str, prefix: str, what: str) -> str:
    """Save the detail record behind every <self> link of a list (applications, call control groups, teams)."""
    saved, failed = 0, []
    for href in _self_urls(_need(dest, f"{source}.xml")):
        path = admin_path(href.replace("+", "%20"))
        ident = href.rstrip("/").split("/")[-1].replace("\\", "_")
        if not path or not _good_name(ident):
            failed.append(href)
            continue
        try:
            _write(client.admin_xml(path), dest / "xml" / f"{prefix}-{ident}.xml")
            saved += 1
        except UccxError as e:
            log.error(f"{what} {ident}: {e}")
            failed.append(ident)
    return _outcome(what, saved, failed, log)


def applications(client, dest, log) -> str:
    return _details(client, dest, log, "applications", "application", "Application details")


def ccgs(client, dest, log) -> str:
    return _details(client, dest, log, "ccgs", "ccg", "Call control group details")


def teams(client, dest, log) -> str:
    return _details(client, dest, log, "teams", "team", "Team details")


def _files(client: UccxClient, dest: Path, log: OpLog, kind: str, sub: str) -> str:
    """Walk the server's prompt or script folders and save every file under dest/<sub>/, keeping the folders."""
    base = dest / sub
    saved, failed = 0, []
    stack = [""]
    while stack:
        folder = stack.pop()
        try:
            root = client.admin_xml(f"{kind}/{folder}")
        except UccxError as e:
            if not folder:
                raise
            log.error(f"{kind} folder {folder}: {e}")
            failed.append(folder)
            continue
        folders = [e.text for e in root.findall(".//FolderName") if _good_name(e.text)]
        names = [e.text for e in root.findall(".//FileName") if _good_name(e.text)]
        (base / folder).mkdir(parents=True, exist_ok=True)
        for name in names:
            if kind == "prompt":
                tail = f"//default/{name}" if not folder else f"{folder}{name}"
                url = f"prompt/download/{tail}"
            else:
                tail = f"{folder}{name}"
                url = f"script/download//default/{tail}"
            try:
                data = client.request("GET", client.admin_url(quote(url, safe="/"))).content
                (base / folder / name).write_bytes(data)
                saved += 1
            except UccxError as e:
                log.error(f"{kind} file {folder}{name}: {e}")
                failed.append(f"{folder}{name}")
        stack += [f"{folder}{f}/" for f in folders]
    log.info(f"{kind} files: {saved} saved")
    return _outcome(f"{kind.capitalize()} files", saved, failed, log)


def prompts(client, dest, log) -> str:
    return _files(client, dest, log, "prompt", "prompts")


def scripts(client, dest, log) -> str:
    return _files(client, dest, log, "script", "scripts")


def _finesse_save(client: UccxClient, dest: Path, api: str, file: str, log: OpLog):
    """Save one Finesse call as finesse/<file>.xml and return its root, or raise UccxError."""
    root = client.finesse_xml(api)
    _write(root, dest / "finesse" / f"{file}.xml")
    log.info(f"Saved Finesse {api}")
    return root


def finesse_settings(client: UccxClient, dest: Path, log: OpLog) -> str:
    saved, failed = 0, []
    for api, file in [("MediaPropertiesLayouts", "callVariableLayouts"), ("ReasonCodes?category=NOT_READY", "notReadyCodes"),
                      ("ReasonCodes?category=LOGOUT", "logoutCodes"), ("WrapUpReasons", "wrapCodes")]:
        try:
            _finesse_save(client, dest, api, file, log)
            saved += 1
        except UccxError as e:
            log.error(f"Finesse {api}: {e}")
            failed.append(api.split("?")[0])
    return _outcome("Finesse settings", saved, failed, log)


def finesse_phone_books(client: UccxClient, dest: Path, log: OpLog) -> str:
    saved, failed = 0, []
    try:
        root = _finesse_save(client, dest, "PhoneBooks", "phonebooks", log)
    except UccxError as e:
        raise UccxError(f"Phone books could not be read. {e}")
    saved += 1
    for book in root.iter("PhoneBook"):
        name = (book.findtext("name") or "").strip()
        contacts = (book.findtext("contacts") or "").replace("/finesse/api/", "")
        if not name or not contacts:
            continue
        try:
            _finesse_save(client, dest, contacts, f"phonebook-{local_name(name)}-contacts", log)
            saved += 1
        except UccxError as e:
            log.error(f"Phone book {name}: {e}")
            failed.append(name)
    return _outcome("Finesse phone books", saved, failed, log)


def finesse_teams(client: UccxClient, dest: Path, log: OpLog) -> str:
    saved, failed = 0, []
    try:
        root = _finesse_save(client, dest, "Teams", "teams", log)
    except UccxError as e:
        raise UccxError(f"Finesse teams could not be read. {e}")
    saved += 1
    for team in root.iter("Team"):
        name = (team.findtext("name") or "").strip()
        uri = (team.findtext("uri") or "").replace("/finesse/api/", "")
        if not name or not uri:
            continue
        safe = local_name(name)
        for suffix, file in [("/ReasonCodes?category=NOT_READY", f"team-NotReady-{safe}"),
                             ("/ReasonCodes?category=LOGOUT", f"team-Logout-{safe}"),
                             ("/WrapUpReasons", f"team-WrapUp-{safe}"), ("/PhoneBooks", f"team-PhoneBook-{safe}"),
                             ("/LayoutConfig", f"team-LayoutConfig-{safe}")]:
            try:
                _finesse_save(client, dest, uri + suffix, file, log)
                saved += 1
            except UccxError as e:
                log.error(f"Finesse team {name} {suffix.lstrip('/')}: {e}")
                failed.append(f"{name} {suffix.lstrip('/').split('?')[0]}")
    return _outcome("Finesse team settings", saved, failed, log)


# (key, label, function). Admin Settings first: the detail areas read the files it saves.
AREAS = [
    ("settings", "Admin Settings", settings),
    ("applications", "Application Details", applications),
    ("ccgs", "Call Control Group Details", ccgs),
    ("teams", "Team Details", teams),
    ("prompts", "Prompt Files", prompts),
    ("scripts", "Script Files", scripts),
    ("finesse_settings", "Finesse Layouts And Codes", finesse_settings),
    ("finesse_phone_books", "Finesse Phone Books", finesse_phone_books),
    ("finesse_teams", "Finesse Team Settings", finesse_teams),
]
