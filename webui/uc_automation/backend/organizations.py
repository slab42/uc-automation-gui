"""Customer organizations, stored as [ORG:<name>] sections in .env/credentials.env.

A platform entry (CUCM, CUC, CUBE, Webex org, RedSky) belongs to an organization through its `org` key.
Entries saved before organizations existed have no `org` and show as Unassigned.
"""

from . import cube_credentials, cuc_connections, cucm_connections, ini_store, redsky_connections, webex_auth
from .paths import CREDENTIALS_PATH

UNASSIGNED = "Unassigned"


def _section(name: str) -> str:
    return f"ORG:{name}"


def list_names() -> list[str]:
    names = [s["identifier"] for s in ini_store.read_sections(CREDENTIALS_PATH) if s["service"] == "ORG"]
    return sorted(names, key=lambda n: (n.lower(), n))


def add(name: str) -> None:
    if name.lower() == UNASSIGNED.lower():
        raise ValueError(f"{UNASSIGNED} is reserved.")
    if name in list_names():
        raise ValueError(f"Organization {name} already exists.")
    ini_store.upsert_section(CREDENTIALS_PATH, _section(name), {"created": "yes"})


def _all_entries() -> list[dict[str, str]]:
    """Every saved platform entry as {platform, name, org}."""
    out = []
    for platform, items in (
        ("CUCM", cucm_connections.list_public()), ("CUC", cuc_connections.list_public()),
        ("CUBE", cube_credentials.list_public()), ("Webex", webex_auth.list_orgs()),
        ("RedSky", redsky_connections.list_public()),
    ):
        out += [{"platform": platform, "name": i["name"], "org": i.get("org", "")} for i in items]
    return out


def delete(name: str) -> None:
    used = [e for e in _all_entries() if e["org"] == name]
    if used:
        raise ValueError(f"{name} still has {len(used)} platform entries. Remove them first.")
    ini_store.delete_section(CREDENTIALS_PATH, _section(name))


def counts() -> dict[str, int]:
    """Platform entries per organization name (Unassigned included when any exist)."""
    names = list_names()
    out = {n: 0 for n in names}
    for e in _all_entries():
        key = e["org"] if e["org"] in out else UNASSIGNED
        out[key] = out.get(key, 0) + 1
    return out


def options() -> list[str]:
    """Names for the organization dropdowns: saved organizations, plus Unassigned while entries need one."""
    names = list_names()
    if any(e["org"] not in names for e in _all_entries()):
        names.append(UNASSIGNED)
    return names


def to_key(org: str) -> str:
    """Dropdown value to stored value (Unassigned is stored as no org)."""
    return "" if org == UNASSIGNED else org


def in_org(items: list[dict[str, str]], org: str, names: list[str]) -> list[dict[str, str]]:
    """Items of one dropdown choice. An org no longer in `names` counts as Unassigned."""
    if org == UNASSIGNED:
        return [i for i in items if i.get("org", "") not in names]
    return [i for i in items if i.get("org", "") == org]


def grouped(items: list[dict[str, str]], names: list[str]) -> list[dict]:
    """Groups for a list shown by organization, alphabetical: {"org": name, "items": [...]} (Unassigned last)."""
    groups = []
    for org in names + [UNASSIGNED]:
        mine = in_org(items, org, names)
        if mine:
            groups.append({"org": org, "items": mine})
    return groups
