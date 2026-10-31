"""Upload a stored UCCX download (see uccx_store) to another UCCX server.

Port of the numbered upload scripts from the old uccxTools (reference only). Each step is a function `step(ctx) -> detail`
that raises UccxError when anything in it failed (the detail then says what), so the page shows OK or Failed per step.
Names are matched on the destination by name, never by ID, except where the ID must match (skills, call control groups,
and the update in place options). Steps log every item. Never log a password. No Reflex imports.
"""

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import requests
from lxml import etree
from lxml import html as lxml_html

from .applog import OpLog
from .uccx_api import UccxClient, UccxError, admin_path, local_name, self_href
from .uccx_connections import UccxConnection

# The old ccg-template.xml: a placeholder call control group, used to walk the ID counter up to the next real ID.
CCG_TEMPLATE = """<callControlGroup>
  <outboundGroup>false</outboundGroup>
  <description>PlaceHolder</description>
  <deviceNamePrefix>ccxph</deviceNamePrefix>
  <numOfCTIPorts>1</numOfCTIPorts>
  <mediaTerminationSupport>false</mediaTerminationSupport>
  <portGroupConfiguration>
    <startingDirectoryNumber>***1</startingDirectoryNumber>
    <devicePool>Default</devicePool>
    <location>Hub_None</location>
    <presenceGroup>Standard Presence group</presenceGroup>
    <redirectCallingSearchSpace>Redirect Party</redirectCallingSearchSpace>
    <requireDTMFReception>true</requireDTMFReception>
  </portGroupConfiguration>
</callControlGroup>"""


@dataclass
class Options:
    original_skill_ids: bool = False  # keep skill IDs as on the origin (third party APIs such as Calabrio need them)
    update_in_place: bool = False  # CSQs, teams and calendars: rename what is there and update by ID (old 6.5, 7.5, 8.5)
    lan_confirmed: bool = False  # call control group import only works between two LAN deployments


@dataclass
class Ctx:
    client: UccxClient
    conn: UccxConnection
    src: Path
    log: OpLog
    opts: Options = field(default_factory=Options)


class Tally:
    """Counts what a step did and turns it into the detail text (or a UccxError when something failed)."""

    def __init__(self, ctx: Ctx):
        self.log = ctx.log
        self.done = 0
        self.failed: list[str] = []
        self.notes: list[str] = []

    def ok(self, label: str, msg: str = "Done") -> None:
        self.done += 1
        self.log.info(f"{label}: {msg}")

    def fail(self, label: str, why) -> None:
        self.failed.append(label)
        self.log.error(f"{label}: {why}")

    def note(self, text: str) -> None:
        self.notes.append(text)
        self.log.warning(text)

    def finish(self) -> str:
        text = f"{self.done} done"
        if self.notes:
            text += ". " + " ".join(self.notes[:4]) + (f" (+{len(self.notes) - 4} more in the log)" if len(self.notes) > 4 else "")
        if self.failed:
            shown = ", ".join(self.failed[:5]) + ("..." if len(self.failed) > 5 else "")
            raise UccxError(f"{text}. {len(self.failed)} failed: {shown}. See the log.")
        return text


# --- small helpers ---

def _load(ctx: Ctx, rel: str):
    """Root element of a stored XML file."""
    path = ctx.src / rel
    if not path.is_file():
        raise UccxError(f"{rel} is not in the stored download.")
    try:
        return etree.parse(str(path)).getroot()
    except etree.XMLSyntaxError as e:
        raise UccxError(f"{rel} is not valid XML ({e}).")


def _files(ctx: Ctx, sub: str, pattern: str) -> list[Path]:
    return sorted((ctx.src / sub).glob(pattern))


def _drop(root, tag: str) -> None:
    """Remove every <tag> below `root`."""
    for el in list(root.iter(tag)):
        parent = el.getparent()
        if parent is not None and el is not root:
            parent.remove(el)


def _names(root, tag: str) -> dict[str, str]:
    """text of each <tag> -> the <self> URL of its parent (a list from the destination)."""
    out = {}
    for el in root.iter(tag):
        parent = el.getparent()
        if parent is not None and el.text and self_href(parent):
            out[el.text] = self_href(parent)
    return out


def _texts(root, tag: str) -> set[str]:
    return {el.text for el in root.iter(tag) if el.text}


def _set_ref(pair, url: str) -> None:
    """Point the <refURL> inside a name+URL element (skillNameUriPair, resourceGroup, csq ...) at `url`."""
    ref = pair.find("refURL")
    if ref is None and len(pair):
        ref = pair[0]
    if ref is not None:
        ref.text = url


def _id_of(href_or_ref: str) -> str:
    return href_or_ref.rstrip("/").split("/")[-1]


def _ok_send(ctx: Ctx, method: str, path: str, tree, ok) -> None:
    ctx.client.send_xml(method, ctx.client.admin_url(path), tree, ok)


def _new_id(resp) -> str:
    """The ID of a thing a POST created: the last part of the URL the server returns."""
    text = (resp.text or "").strip() or resp.headers.get("Location", "")
    return _id_of(text)


def _xml(tag: str, **children) -> etree._Element:
    el = etree.Element(tag)
    for k, v in children.items():
        etree.SubElement(el, k).text = v
    return el


# --- optional first step ---

def delete_triggers(ctx: Ctx) -> str:
    t = Tally(ctx)
    for trig in list(ctx.client.admin_xml("trigger").iter("trigger")):
        dn = trig.findtext("directoryNumber") or "?"
        path = admin_path(self_href(trig))
        if not path:
            t.fail(dn, "no link to delete")
            continue
        try:
            ctx.client.request("DELETE", ctx.client.admin_url(path))
            t.ok(dn, "Trigger deleted")
        except UccxError as e:
            t.fail(dn, e)
    return t.finish()


# --- 1 call control groups ---

def _ccg_map_path(ctx: Ctx) -> Path:
    return ctx.src / f"ccg-id-map-{local_name(ctx.conn.server)}.json"


def ccg_id_map(ctx: Ctx) -> dict[str, str]:
    """Origin call control group ID -> ID it got on this destination (only those that changed)."""
    try:
        return json.loads(_ccg_map_path(ctx).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _ccg_ids(client: UccxClient) -> list[int]:
    root = client.admin_xml("callControlGroup")
    return sorted(int(e.findtext("id")) for e in root.iter("callControlGroup") if (e.findtext("id") or "").isdigit())


def _ccg_add(client: UccxClient, tree) -> None:
    _drop(tree, "self")
    _drop(tree, "id")
    client.send_xml("POST", client.admin_url("callControlGroup"), tree, ok=(201, 202, 206))


def _ccg_built(client: UccxClient, ccg_id: int) -> bool:
    """Wait for an add or update to finish (201 built, 206 in progress, 200 or 410 then check it exists)."""
    for _ in range(90):
        try:
            resp = client.request("GET", client.admin_url(f"callControlGroup/{ccg_id}/status"), ok=(200, 201, 206, 410))
        except UccxError:
            return False
        if resp.status_code == 201:
            return True
        if resp.status_code == 206:
            time.sleep(2)
            continue
        try:
            client.request("GET", client.admin_url(f"callControlGroup/{ccg_id}"))
            return True
        except UccxError:
            return False
    return False


def _ccg_update(ctx: Ctx, ccg_id: int, tree) -> bool:
    client = ctx.client
    if not _ccg_built(client, ccg_id):
        ctx.log.error(f"Call control group {ccg_id} is not ready to update")
        return False
    for tag in ("self", "id", "listOfCTIPorts"):
        _drop(tree, tag)
    try:
        client.send_xml("PUT", client.admin_url(f"callControlGroup/{ccg_id}"), tree, ok=(202,))
    except UccxError as e:
        ctx.log.error(f"Update of call control group {ccg_id} failed: {e}")
        return False
    time.sleep(1)
    return _ccg_built(client, ccg_id)


def ccgs(ctx: Ctx) -> str:
    if not ctx.opts.lan_confirmed:
        raise UccxError("Confirm that both servers are LAN deployments to import call control groups.")
    client, t = ctx.client, Tally(ctx)
    backup = _load(ctx, "xml/ccgs.xml")
    to_add = sorted(int(e.findtext("id")) for e in backup.iter("callControlGroup") if (e.findtext("id") or "").isdigit())
    if not to_add:
        return "No call control groups in the download"
    top, current, unused, moved = to_add[-1], 0, [], {}
    # Add placeholders until the destination's counter reaches the highest origin ID; each placeholder that lands on
    # an origin ID becomes that group, the rest are reused later (so no ID is wasted).
    for _ in range(top * 2 + 20):
        if current >= top:
            break
        try:
            _ccg_add(client, etree.fromstring(CCG_TEMPLATE))
        except UccxError as e:
            t.fail("Placeholder", f"cannot add call control groups here: {e}")
            break
        if current == 0:
            time.sleep(5)
        else:
            _ccg_built(client, current + 1)
        current = _ccg_ids(client)[-1]
        if current in to_add:
            if _ccg_update(ctx, current, _load(ctx, f"xml/ccg-{current}.xml")):
                to_add.remove(current)
                t.ok(f"Call control group {current}")
        else:
            unused.append(current)
    for old in list(to_add):
        tree = _load(ctx, f"xml/ccg-{old}.xml")
        if unused:
            new = unused[0]
            if _ccg_update(ctx, new, tree):
                unused.pop(0)
                moved[str(old)] = str(new)
                t.ok(f"Call control group {old}", f"Used spare ID {new}")
            else:
                t.fail(f"Call control group {old}", "update failed")
        else:
            new = _ccg_ids(client)[-1] + 1
            try:
                _ccg_add(client, tree)
            except UccxError as e:
                t.fail(f"Call control group {old}", e)
                continue
            if _ccg_built(client, new):
                moved[str(old)] = str(new)
                t.ok(f"Call control group {old}", f"Created as {new}")
            else:
                t.fail(f"Call control group {old}", "not built")
    if moved:
        _ccg_map_path(ctx).write_text(json.dumps(moved), encoding="utf-8")
        t.note("Call control groups with a new ID (old to new): " + ", ".join(f"{o} to {n}" for o, n in moved.items()) +
               ". Triggers uploaded later use the new IDs.")
    return t.finish()


# --- 2 supervisor role (the old script drives the appadmin web pages) ---

def supervisors(ctx: Ctx) -> str:
    t = Tally(ctx)
    role = "Supervisor"
    users = [r.findtext("userID") for r in _load(ctx, "xml/resources.xml").iter("resource") if r.findtext("type") == "2"]
    users = [u for u in users if u]
    if not users:
        return "No supervisors in the download"
    base = f"https://{ctx.conn.server}/appadmin"
    s = requests.Session()
    s.verify = False
    try:
        s.get(f"{base}/main", timeout=60)
        resp = s.post(f"{base}/JavaScriptServlet", timeout=60, headers={"Referer": f"{base}/main", "FETCH-CSRF-TOKEN": "1"})
        text = resp.text.strip()
        token = text.split(":", 1)[1] if ":" in text else text[10:]
        resp = s.post(f"{base}/j_security_check", timeout=60,
                      data={"j_username": ctx.conn.username, "j_password": ctx.conn.password})
    except requests.exceptions.RequestException as e:
        raise UccxError(f"Cannot reach the UCCX administration pages on {ctx.conn.server} ({e.__class__.__name__}).")
    if resp.status_code >= 400:
        raise UccxError(f"Login to the UCCX administration pages failed (HTTP {resp.status_code}).")
    for user in users:
        try:
            resp = s.post(f"{base}/LDAPSetup?request_type=ldapsetup.waitpage.usermaintenance&wizard=&isonload=false",
                          timeout=60, headers={"Referer": f"{base}/main", "CSRFTOKEN": token},
                          data={"request_type": "ldapsetup.next.usermaintenance", "chkLoginUser": "false",
                                "search_criteria": user, "CSRFTOKEN": token})
            if resp.status_code != 200:
                t.fail(user, f"search failed (HTTP {resp.status_code})")
                continue
            link = None
            for td in lxml_html.fromstring(resp.content).iter("td"):
                if td.text_content().strip() == user and td.find(".//a") is not None:
                    link = td.find(".//a").get("href", "")
                    break
            query = parse_qs(urlparse(link or "").query)
            if not link or query.get("uId", [""])[0] != user:
                t.fail(user, "not found. Make sure the user is an agent.")
                continue
            caps = query.get("cap", [""])[0]
            if role in caps:
                t.note(f"{user} was already a supervisor.")
                continue
            resp = s.post(f"{base}/LDAPSetup", timeout=60, headers={"Referer": f"{base}/main"},
                          data={"request_type": "ldapsetup.userupdate", "users": f"{caps},{role}",
                                "request_type_axl": "ldapsetup.next.usermaintenance", "selected_user": user,
                                "setup": "null", "deploymentType": "1", "userView": "false", "chkLoginUser": "false",
                                "CSRFTOKEN": token})
            if resp.status_code == 200:
                t.ok(user, "Supervisor role added")
            else:
                t.fail(user, f"update failed (HTTP {resp.status_code})")
        except requests.exceptions.RequestException as e:
            t.fail(user, e.__class__.__name__)
        except (ValueError, etree.ParserError) as e:
            t.fail(user, f"unreadable answer ({e})")
    return t.finish()


# --- 3 skills ---

def _add_skill(client: UccxClient, name: str) -> str:
    resp = client.send_xml("POST", client.admin_url("skill"), _xml("Skill", skillName=name), ok=(201,))
    return _new_id(resp)


def _skills_original_ids(ctx: Ctx, skills: dict[int, str], t: Tally) -> None:
    """Add placeholder skills until the destination's counter reaches each origin ID, naming the ones that land on one."""
    client = ctx.client
    wanted, current, bad, n = dict(skills), 0, 0, 0
    top = max(wanted)
    while current < top and bad < 5:
        n += 1
        try:
            current = int(_add_skill(client, f"placeholder-{n}"))
        except (UccxError, ValueError) as e:
            bad += 1
            ctx.log.error(f"Placeholder skill: {e}")
            continue
        if current in wanted:
            name = wanted.pop(current)
            try:
                client.send_xml("PUT", client.admin_url(f"skill/{current}"), _xml("Skill", skillName=name), ok=(200,))
                t.ok(name, f"Skill {current}")
            except UccxError as e:
                t.fail(name, e)
        else:
            try:
                client.request("DELETE", client.admin_url(f"skill/{current}"))
            except UccxError as e:
                ctx.log.error(f"Could not remove unneeded placeholder skill {current}: {e}")
    for old, name in wanted.items():  # IDs that could not be reached: add with a new ID
        try:
            new = _add_skill(client, name)
            t.ok(name, f"Old ID {old}, new ID {new}")
            t.note(f"Skill {name} has a new ID: {old} to {new}.")
        except UccxError as e:
            t.fail(name, e)


def skills(ctx: Ctx) -> str:
    t = Tally(ctx)
    src = _load(ctx, "xml/skills.xml")
    existing = _texts(ctx.client.admin_xml("skill"), "skillName")
    items = {}
    for el in src.iter("skillName"):
        sid = el.getparent().findtext("skillId") or ""
        if el.text and el.text in existing:
            t.note(f"Skill {el.text} already exists.")
        elif el.text and sid.isdigit():
            items[int(sid)] = el.text
    if not items:
        return t.finish()
    if ctx.opts.original_skill_ids:
        _skills_original_ids(ctx, items, t)
    else:
        for old, name in sorted(items.items()):
            try:
                t.ok(name, f"Old ID {old}, new ID {_add_skill(ctx.client, name)}")
            except UccxError as e:
                t.fail(name, e)
    return t.finish()


# --- 4 resource groups ---

def resource_groups(ctx: Ctx) -> str:
    t = Tally(ctx)
    existing = _texts(ctx.client.admin_xml("resourceGroup"), "name")
    for el in _load(ctx, "xml/resourceGroups.xml").iter("name"):
        if not el.text:
            continue
        if el.text in existing:
            t.note(f"Resource group {el.text} already exists.")
            continue
        try:
            ctx.client.send_xml("POST", ctx.client.admin_url("resourceGroup"), _xml("resourceGroup", name=el.text), ok=(201,))
            t.ok(el.text)
        except UccxError as e:
            t.fail(el.text, e)
    return t.finish()


# --- 5 resources ---

def resources(ctx: Ctx) -> str:
    """Update the agents that already exist on the destination (they come from CUCM) with the origin's settings."""
    client, t = ctx.client, Tally(ctx)
    on_dest = {r.findtext("userID"): r for r in client.admin_xml("resource").iter("resource")}
    skill_urls = _names(client.admin_xml("skill"), "skillName")
    group_urls = _names(client.admin_xml("resourceGroup"), "name")
    for res in list(_load(ctx, "xml/resources.xml").iter("resource")):
        uid = res.findtext("userID") or ""
        current = on_dest.get(uid)
        if current is None:
            t.note(f"{uid} is not on the destination, skipped.")
            continue
        ext = res.find("extension")
        if ext is not None:
            ext.text = current.findtext("extension")
        for pair in list(res.iter("skillNameUriPair")):
            url = skill_urls.get(pair.get("name", ""))
            if url:
                _set_ref(pair, url)
            else:
                t.note(f"{uid}: skill {pair.get('name')} is not on the destination, left out.")
                pair.getparent().getparent().remove(pair.getparent())
        group = res.find("resourceGroup")
        if group is not None:
            url = group_urls.get(group.get("name", ""))
            if not url:
                t.fail(uid, f"resource group {group.get('name')} is not on the destination")
                continue
            _set_ref(group, url)
        team = res.find("team")
        if team is not None:
            team.set("name", "Default")
            _set_ref(team, client.admin_url("team/1"))
        for tag in ("primarySupervisorOf", "secondarySupervisorOf"):
            old = res.find(tag)
            if old is not None:
                res.remove(old)
            etree.SubElement(res, tag)
        _drop(res, "self")
        try:
            _ok_send(ctx, "PUT", f"resource/{quote(uid, safe='')}", res, ok=(200,))
            t.ok(uid)
        except UccxError as e:
            t.fail(uid, e)
    return t.finish()


# --- 6 CSQs ---

def _map_csq(csq, skill_urls: dict, group_urls: dict) -> str:
    """Point the CSQ's skill and resource group references at the destination. Returns what is missing ('' if nothing)."""
    for pair in csq.iter("skillNameUriPair"):
        url = skill_urls.get(pair.get("name", ""))
        if not url:
            return f"skill {pair.get('name')} is not on the destination"
        _set_ref(pair, url)
    for pair in csq.iter("resourceGroupNameUriPair"):
        url = group_urls.get(pair.get("name", ""))
        if not url:
            return f"resource group {pair.get('name')} is not on the destination"
        _set_ref(pair, url)
    return ""


def csqs(ctx: Ctx) -> str:
    client, t = ctx.client, Tally(ctx)
    skill_urls = _names(client.admin_xml("skill"), "skillName")
    group_urls = _names(client.admin_xml("resourceGroup"), "name")
    src = _load(ctx, "xml/csqs.xml")
    if ctx.opts.update_in_place:
        # Free every name first (so a renamed CSQ cannot clash), then write each origin CSQ over the ID it had.
        for cur in list(client.admin_xml("csq").iter("csq")):
            cid = cur.findtext("id") or ""
            cur.find("name").text = f"Placeholder {cid}"
            _drop(cur, "self")
            try:
                _ok_send(ctx, "PUT", f"csq/{cid}", cur, ok=(200, 201, 202, 206))
            except UccxError as e:
                ctx.log.error(f"Rename of CSQ {cid} failed: {e}")
        for csq in list(src.iter("csq")):
            cid, name = csq.findtext("id") or "", csq.findtext("name") or ""
            missing = _map_csq(csq, skill_urls, group_urls)
            if missing:
                t.fail(name, missing)
                continue
            _drop(csq, "self")
            try:
                _ok_send(ctx, "PUT", f"csq/{cid}", csq, ok=(200, 201, 202, 206))
                t.ok(name, f"Updated ID {cid}")
            except UccxError as e:
                t.fail(name, e)
        return t.finish()
    existing = _texts(client.admin_xml("csq"), "name")
    for csq in list(src.iter("csq")):
        name = csq.findtext("name") or ""
        if name in existing:
            t.note(f"CSQ {name} already exists.")
            continue
        missing = _map_csq(csq, skill_urls, group_urls)
        if missing:
            t.fail(name, missing)
            continue
        _drop(csq, "self")
        _drop(csq, "id")
        try:
            _ok_send(ctx, "POST", "csq", csq, ok=(201,))
            t.ok(name)
        except UccxError as e:
            t.fail(name, e)
    return t.finish()


# --- 7 teams ---

def _prep_team(ctx: Ctx, team, users: set[str], csq_urls: dict, skipped: list[str]) -> str:
    """Point a team's supervisors, agents and CSQs at the destination and drop what is not there. Returns a reason
    when the team cannot be uploaded ('' when it can)."""
    client = ctx.client
    name = team.findtext("teamname") or ""
    _drop(team, "self")
    for tag in ("primarySupervisor", "secondrySupervisor", "resource"):
        for el in list(team.iter(tag)):
            ref = el.find("refURL")
            uid = _id_of(ref.text or "") if ref is not None else ""
            user = uid.replace("%40", "@")
            if user not in users:
                if tag == "primarySupervisor":
                    return f"primary supervisor {user} is not on the destination"
                el.getparent().remove(el)
                skipped.append(f"{name}: {user}")
            else:
                ref.text = client.admin_url(f"resource/{uid}")
    for csq in list(team.iter("csq")):
        url = csq_urls.get(csq.get("name", ""))
        if url:
            _set_ref(csq, url)
        else:
            csq.getparent().remove(csq)
            skipped.append(f"{name}: CSQ {csq.get('name')}")
    return ""


def teams(ctx: Ctx) -> str:
    client, t = ctx.client, Tally(ctx)
    csq_urls = _names(client.admin_xml("csq"), "name")
    users = {r.findtext("userID") for r in client.admin_xml("resource").iter("resource")}
    skipped: list[str] = []
    paths = _files(ctx, "xml", "team-*.xml")
    if ctx.opts.update_in_place:
        for cur in list(client.admin_xml("team").iter("team")):
            tid = cur.findtext("teamId") or ""
            if tid == "1":
                continue
            cur.find("teamname").text = f"Placeholder {tid}"
            _drop(cur, "self")
            try:
                _ok_send(ctx, "PUT", f"team/{tid}", cur, ok=(200, 201, 202, 206))
            except UccxError as e:
                ctx.log.error(f"Rename of team {tid} failed: {e}")
    else:
        existing = _texts(client.admin_xml("team"), "teamname")
    for path in paths:
        team = etree.parse(str(path)).getroot()
        name = team.findtext("teamname") or path.stem
        if name == "Default":
            continue
        if not ctx.opts.update_in_place and name in existing:
            t.note(f"Team {name} already exists.")
            continue
        tid = team.findtext("teamId") or ""
        why = _prep_team(ctx, team, users, csq_urls, skipped)
        if why:
            t.fail(name, why)
            continue
        try:
            if ctx.opts.update_in_place:
                _ok_send(ctx, "PUT", f"team/{tid}", team, ok=(200, 201, 202, 206))
                t.ok(name, f"Updated ID {tid}")
            else:
                _drop(team, "teamId")
                _ok_send(ctx, "POST", "team", team, ok=(201,))
                t.ok(name)
        except UccxError as e:
            t.fail(name, e)
    if skipped:
        t.note(f"{len(skipped)} agents, supervisors or CSQs were not on the destination and were left out of their teams "
               "(listed in the log).")
        for s in skipped:
            ctx.log.warning(f"Left out of team - {s}")
    return t.finish()


# --- 8 calendars ---

def calendars(ctx: Ctx) -> str:
    client, t = ctx.client, Tally(ctx)
    src = _load(ctx, "xml/calendars.xml")
    _drop(src, "self")
    if not ctx.opts.update_in_place:
        _drop(src, "id")
    today = date.today()
    for tag in list(src.iter("date")):  # holidays already past are not worth uploading
        try:
            past = datetime.strptime((tag.text or "").strip(), "%Y-%m-%d").date() < today
        except ValueError:
            continue
        if past and tag.getparent() is not None and tag.getparent().getparent() is not None:
            holiday = tag.getparent()
            holiday.getparent().remove(holiday)
    existing = set() if ctx.opts.update_in_place else _texts(client.admin_xml("calendar"), "name")
    for cal in list(src.iter("calendar")):
        name = cal.findtext("name") or ""
        if name in existing:
            t.note(f"Calendar {name} already exists.")
            continue
        try:
            if ctx.opts.update_in_place:
                _ok_send(ctx, "PUT", f"calendar/{cal.findtext('calId')}", cal, ok=(200,))
                t.ok(name, "Updated")
            else:
                _ok_send(ctx, "POST", "calendar", cal, ok=(201,))
                t.ok(name)
        except UccxError as e:
            t.fail(name, e)
    return t.finish()


# --- 9 scripts and prompts ---

def _upload_files(ctx: Ctx, api: str, base: Path, t: Tally) -> None:
    client = ctx.client
    if not base.is_dir():
        return
    kind = api.capitalize()
    dirs = sorted((p for p in base.rglob("*") if p.is_dir()), key=lambda p: len(p.relative_to(base).parts))
    for d in dirs:
        rel = d.relative_to(base).as_posix()
        parent, _, name = rel.rpartition("/")
        tree = etree.fromstring(f"<Files><{kind}><Folder/></{kind}></Files>")
        folder = tree.find(f".//Folder")
        etree.SubElement(folder, "path").text = f"/{parent}" if parent else "/"
        etree.SubElement(folder, "FolderName").text = name
        try:
            client.send_xml("POST", client.admin_url(api), tree, ok=(201,))
        except UccxError:
            ctx.log.info(f"{kind} folder /{rel} not created (it may already exist)")
    for p in sorted(base.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in (".wav", ".aef"):
            continue
        rel = p.relative_to(base).as_posix()
        folder = rel.rpartition("/")[0]
        label = f"{kind} /{rel}"
        try:
            client.request("DELETE", client.admin_url(quote(f"{api}/{rel}", safe="/")))
        except UccxError:
            pass  # nothing to replace
        try:
            with open(p, "rb") as fh:
                client.request("POST", client.admin_url(f"{api}/uploadFile"), ok=(201,), files={"file": (p.name, fh)})
        except UccxError as e:
            ctx.log.warning(f"{label}: upload answered {e} (the file may already be there)")
        tree = etree.fromstring(f"<Files><{kind}><File/></{kind}></Files>")
        entry = tree.find(".//File")
        etree.SubElement(entry, "path").text = f"/{folder}/" if folder else "/"
        etree.SubElement(entry, "FileName").text = p.name
        try:
            client.send_xml("POST", client.admin_url(api), tree, ok=(201,))
            t.ok(label)
        except UccxError as e:
            t.fail(label, e)


def files(ctx: Ctx) -> str:
    t = Tally(ctx)
    _upload_files(ctx, "script", ctx.src / "scripts", t)
    _upload_files(ctx, "prompt", ctx.src / "prompts", t)
    return t.finish()


# --- 10 to 12 applications and triggers ---

def applications(ctx: Ctx) -> str:
    client, t = ctx.client, Tally(ctx)
    in_use = _texts(client.admin_xml("application"), "id")
    for path in _files(ctx, "xml", "application-*.xml"):
        app = etree.parse(str(path)).getroot()
        name = app.findtext("applicationName") or path.stem
        _drop(app, "self")
        script = app.find(".//script")
        if script is not None and script.text and not script.text.startswith("SCRIPT["):
            script.text = f"SCRIPT[{script.text}]"
        for tag in app.iter("id"):
            if tag.text in in_use:  # take the first free ID
                tag.text = next(str(i) for i in range(len(in_use) + 1) if str(i) not in in_use)
            in_use.add(tag.text)
        try:
            _ok_send(ctx, "POST", "application", app, ok=(201,))
            t.ok(name)
        except UccxError as e:
            t.fail(name, e)
    return t.finish()


def _trigger_step(ctx: Ctx, rel: str, tag: str, api: str, key: str, with_groups: bool) -> str:
    client, t = ctx.client, Tally(ctx)
    app_urls = _names(client.admin_xml("application"), "applicationName")
    moved = ccg_id_map(ctx)
    for trig in list(_load(ctx, rel).iter(tag)):
        label = trig.findtext(key) or "?"
        _drop(trig, "self")
        app = trig.find("application")
        url = app_urls.get(app.get("name", "")) if app is not None else None
        if not url:
            t.fail(label, f"application {app.get('name') if app is not None else '?'} is missing on the destination")
            continue
        _set_ref(app, url.replace("+", "%20"))
        if with_groups:
            for el in list(trig.iter("callControlGroup")) + list(trig.iter("dialogGroup")):
                ref = el.find("refURL")
                if ref is not None:
                    gid = _id_of(ref.text or "")
                    ref.text = client.admin_url(f"callControlGroup/{moved.get(gid, gid)}")
        try:
            _ok_send(ctx, "POST", api, trig, ok=(201,))
            t.ok(label, f"For {app.get('name')}")
        except UccxError as e:
            t.fail(label, e)
    return t.finish()


def triggers(ctx: Ctx) -> str:
    return _trigger_step(ctx, "xml/triggers.xml", "trigger", "trigger", "directoryNumber", True)


def http_triggers(ctx: Ctx) -> str:
    return _trigger_step(ctx, "xml/httpTriggers.xml", "httpTrigger", "httpTrigger", "name", False)


# --- 13 to 17 Finesse ---

def _finesse_post(ctx: Ctx, api: str, tree, ok=(200,)) -> None:
    ctx.client.send_xml("POST", ctx.client.finesse_url(api), tree, ok=ok)


def call_variable_layouts(ctx: Ctx) -> str:
    t = Tally(ctx)
    for layout in list(_load(ctx, "finesse/callVariableLayouts.xml").iter("MediaPropertiesLayout")):
        name = layout.findtext("name") or "?"
        _drop(layout, "uri")
        try:
            if layout.findtext("type") == "DEFAULT":
                ctx.client.send_xml("PUT", ctx.client.finesse_url("MediaPropertiesLayout/default"), layout, ok=(200,))
                t.ok(name, "Default layout updated")
            else:
                _finesse_post(ctx, "MediaPropertiesLayout", layout)
                t.ok(name)
        except UccxError as e:
            t.fail(name, e)
    return t.finish()


def reason_codes(ctx: Ctx) -> str:
    t = Tally(ctx)
    for rel in ("finesse/notReadyCodes.xml", "finesse/logoutCodes.xml"):
        for reason in list(_load(ctx, rel).iter("ReasonCode")):
            label = reason.findtext("label") or "?"
            system = reason.findtext("systemCode")
            if system == "true":
                continue  # the destination has its own system codes
            _drop(reason, "uri")
            _drop(reason, "systemCode")
            try:
                _finesse_post(ctx, "ReasonCode", reason)
                t.ok(label)
            except UccxError as e:
                t.fail(label, e)
    return t.finish()


def wrap_up_codes(ctx: Ctx) -> str:
    t = Tally(ctx)
    for reason in list(_load(ctx, "finesse/wrapCodes.xml").iter("WrapUpReason")):
        label = reason.findtext("label") or "?"
        _drop(reason, "uri")
        try:
            _finesse_post(ctx, "WrapUpReason", reason)
            t.ok(label)
        except UccxError as e:
            t.fail(label, e)
    return t.finish()


def phone_books(ctx: Ctx) -> str:
    client, t = ctx.client, Tally(ctx)
    books = list(_load(ctx, "finesse/phonebooks.xml").iter("PhoneBook"))
    for book in books:
        name = book.findtext("name") or "?"
        _drop(book, "uri")
        _drop(book, "contacts")
        try:
            _finesse_post(ctx, "PhoneBook", book)
            t.ok(name)
        except UccxError as e:
            t.fail(name, e)
    on_dest = {b.findtext("name"): b.findtext("contacts") for b in client.finesse_xml("PhoneBooks").iter("PhoneBook")}
    for book in books:
        name = book.findtext("name") or "?"
        path = ctx.src / "finesse" / f"phonebook-{local_name(name)}-contacts.xml"
        url = on_dest.get(name)
        if not path.is_file() or not url:
            continue
        contacts = etree.parse(str(path)).getroot()
        _drop(contacts, "uri")
        try:
            client.send_xml("PUT", f"https://{client.server}:8445{url}", contacts, ok=(200,))
            t.ok(f"{name} contacts")
        except UccxError as e:
            t.fail(f"{name} contacts", e)
    return t.finish()


def finesse_teams(ctx: Ctx) -> str:
    """Per team: desktop layout, logout and not ready codes, wrap-up codes, phone books (matched by name or code)."""
    client, t = ctx.client, Tally(ctx)
    dest_teams = {x.findtext("name"): x.findtext("uri") for x in client.finesse_xml("Teams").iter("Team")}
    codes = {x.findtext("code"): x.findtext("uri") for x in client.finesse_xml("ReasonCodes?category=ALL").iter("ReasonCode")}
    wraps = {x.findtext("label"): x.findtext("uri") for x in client.finesse_xml("WrapUpReasons").iter("WrapUpReason")}
    books = {x.findtext("name"): x.findtext("uri") for x in client.finesse_xml("PhoneBooks").iter("PhoneBook")}

    def refs(path: Path, tag: str, key: str, lookup: dict, outer: str, inner: str):
        out = etree.Element(outer)
        for el in etree.parse(str(path)).getroot().iter(tag):
            uri = lookup.get(el.findtext(key))
            if uri:
                etree.SubElement(etree.SubElement(out, inner), "uri").text = uri
        return out

    for team in _load(ctx, "finesse/teams.xml").iter("Team"):
        name = team.findtext("name") or ""
        uri = dest_teams.get(name)
        if not uri:
            t.note(f"Finesse team {name} is not on the destination, skipped.")
            continue
        safe = local_name(name)
        for kind, file, tag, key, lookup, outer, inner, suffix in [
            ("Desktop layout", f"team-LayoutConfig-{safe}.xml", None, None, None, None, None, "/LayoutConfig"),
            ("Logout codes", f"team-Logout-{safe}.xml", "ReasonCode", "code", codes, "ReasonCodes", "ReasonCode",
             "/ReasonCodes?category=LOGOUT"),
            ("Not ready codes", f"team-NotReady-{safe}.xml", "ReasonCode", "code", codes, "ReasonCodes", "ReasonCode",
             "/ReasonCodes?category=NOT_READY"),
            ("Wrap-up codes", f"team-WrapUp-{safe}.xml", "WrapUpReason", "label", wraps, "WrapUpReasons", "WrapUpReason",
             "/WrapUpReasons"),
            ("Phone books", f"team-PhoneBook-{safe}.xml", "PhoneBook", "name", books, "PhoneBooks", "PhoneBook",
             "/PhoneBooks"),
        ]:
            path = ctx.src / "finesse" / file
            if not path.is_file():
                continue
            label = f"{name} {kind.lower()}"
            try:
                body = (etree.parse(str(path)).getroot() if tag is None
                        else refs(path, tag, key, lookup, outer, inner))
                payload = etree.tostring(body, encoding="unicode", pretty_print=True).encode("utf-8")
                client.request("PUT", client.finesse_url(uri.replace("/finesse/api/", "") + suffix), ok=(200,),
                               data=payload, headers={"Content-Type": "application/xml"})
                t.ok(label)
            except (UccxError, etree.XMLSyntaxError) as e:
                t.fail(label, e)
    return t.finish()


# (key, label, function). Order is the order they run.
STEPS = [
    ("delete_triggers", "Delete Existing Triggers", delete_triggers),
    ("ccgs", "Call Control Groups", ccgs),
    ("supervisors", "Supervisor Role", supervisors),
    ("skills", "Skills", skills),
    ("resource_groups", "Resource Groups", resource_groups),
    ("resources", "Resources (Agents)", resources),
    ("csqs", "Contact Service Queues", csqs),
    ("teams", "Teams", teams),
    ("calendars", "Calendars", calendars),
    ("files", "Scripts And Prompts", files),
    ("applications", "Applications", applications),
    ("triggers", "Triggers", triggers),
    ("http_triggers", "HTTP Triggers", http_triggers),
    ("call_variable_layouts", "Finesse Call Variable Layouts", call_variable_layouts),
    ("reason_codes", "Finesse Reason Codes", reason_codes),
    ("wrap_up_codes", "Finesse Wrap-Up Codes", wrap_up_codes),
    ("phone_books", "Finesse Phone Books", phone_books),
    ("finesse_teams", "Finesse Team Settings", finesse_teams),
]
