"""Saved CUCM connections, stored as [CUCM:<name>] sections in .env/credentials.env.

Keys: server, username, password, version (detected CUCM major release),
schema_version (AXL schema folder used for that release), subscribers (comma separated
`host` or `host|em`, `|em` marks a subscriber running Extension Mobility), sme (`yes` when the cluster is a SME cluster).
"""

from dataclasses import dataclass, field

from . import ini_store
from .paths import CREDENTIALS_PATH


@dataclass
class CucmConnection:
    name: str
    server: str
    username: str
    password: str
    version: str = ""
    schema_version: str = ""
    subscribers: list[dict[str, str]] = field(default_factory=list)
    sme: bool = False


def parse_subscribers(raw: str) -> list[dict[str, str]]:
    """'a|em,b' -> [{'host': 'a', 'em': 'yes'}, {'host': 'b', 'em': 'no'}]."""
    out = []
    for item in raw.split(","):
        host, _, flag = item.strip().partition("|")
        if host.strip():
            out.append({"host": host.strip(), "em": "yes" if flag.strip().lower() == "em" else "no"})
    return out


def format_subscribers(subs: list[dict[str, str]]) -> str:
    return ",".join(s["host"] + ("|em" if s.get("em") == "yes" else "") for s in subs)


def _section(name: str) -> str:
    return f"CUCM:{name}"


def list_public() -> list[dict[str, str]]:
    """Connections without secrets, safe for the browser."""
    out = []
    for s in ini_store.read_sections(CREDENTIALS_PATH):
        if s["service"] != "CUCM" or s["identifier"] == "default":
            continue
        f = s["fields"]
        out.append({
            "name": s["identifier"],
            "server": f.get("server", ""),
            "username": f.get("username", ""),
            "version": f.get("version", ""),
            "schema_version": f.get("schema_version", ""),
            "org": f.get("org", ""),
            "subscribers": f.get("subscribers", ""),
            "sme": "yes" if f.get("sme", "").lower() == "yes" else "no",
            "has_password": "yes" if s["secrets"].get("password") else "no",
        })
    return out


def load(name: str) -> CucmConnection | None:
    kv = ini_store.read_section(CREDENTIALS_PATH, _section(name))
    if not kv.get("server"):
        return None
    return CucmConnection(
        name=name,
        server=kv.get("server", ""),
        username=kv.get("username", ""),
        password=kv.get("password", ""),
        version=kv.get("version", ""),
        schema_version=kv.get("schema_version", ""),
        subscribers=parse_subscribers(kv.get("subscribers", "")),
        sme=kv.get("sme", "").lower() == "yes",
    )


def save(name: str, server: str, username: str, password: str | None,
         version: str | None = None, schema_version: str | None = None,
         org: str | None = None, subscribers: list[dict[str, str]] | None = None,
         sme: bool | None = None) -> None:
    """password None/'' keeps the stored one. subscribers/sme None keep the stored value. Changing server/username clears stale version info."""
    old = load(name)
    values: dict[str, str | None] = {"server": server, "username": username}
    if org is not None:
        values["org"] = org
    if subscribers is not None:
        values["subscribers"] = format_subscribers(subscribers)
    if sme is not None:
        values["sme"] = "yes" if sme else "no"
    if password:
        values["password"] = password
    elif old is None:
        values["password"] = ""
    if version is not None:
        values["version"] = version
        values["schema_version"] = schema_version or ""
    elif old and (old.server != server or old.username != username):
        values["version"] = ""
        values["schema_version"] = ""
    ini_store.upsert_section(CREDENTIALS_PATH, _section(name), values)


def delete(name: str) -> bool:
    return ini_store.delete_section(CREDENTIALS_PATH, _section(name))
