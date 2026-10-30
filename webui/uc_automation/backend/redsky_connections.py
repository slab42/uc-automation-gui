"""Saved RedSky connections, stored as [REDSKY:<name>] sections in .env/credentials.env.

Keys: username, password, org_id (the RedSky organization the scripts work in).
The CLI reads [REDSKY:default] from the same file.
"""

from dataclasses import dataclass

from . import ini_store
from .paths import CREDENTIALS_PATH


@dataclass
class RedskyConnection:
    name: str
    username: str
    password: str
    org_id: str


def _section(name: str) -> str:
    return f"REDSKY:{name}"


def list_public() -> list[dict[str, str]]:
    """Connections without secrets, safe for the browser."""
    out = []
    for s in ini_store.read_sections(CREDENTIALS_PATH):
        if s["service"] != "REDSKY":
            continue
        f = s["fields"]
        out.append({
            "name": s["identifier"],
            "username": f.get("username", ""),
            "org_id": f.get("org_id", ""),
            "org": f.get("org", ""),
            "has_password": "yes" if s["secrets"].get("password") else "no",
        })
    return out


def load(name: str) -> RedskyConnection | None:
    kv = ini_store.read_section(CREDENTIALS_PATH, _section(name))
    if not kv.get("username"):
        return None
    return RedskyConnection(
        name=name,
        username=kv.get("username", ""),
        password=kv.get("password", ""),
        org_id=kv.get("org_id", ""),
    )


def save(name: str, username: str, password: str | None, org_id: str, org: str | None = None) -> None:
    """password None/'' keeps the stored one."""
    old = load(name)
    values: dict[str, str | None] = {"username": username, "org_id": org_id}
    if org is not None:
        values["org"] = org
    if password:
        values["password"] = password
    elif old is None:
        values["password"] = ""
    ini_store.upsert_section(CREDENTIALS_PATH, _section(name), values)


def delete(name: str) -> bool:
    return ini_store.delete_section(CREDENTIALS_PATH, _section(name))
