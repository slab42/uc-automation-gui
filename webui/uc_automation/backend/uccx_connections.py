"""Saved UCCX connections, stored as [UCCX:<name>] sections in .env/credentials.env.

Keys: server, username, password, org. The admin API (https://<server>/adminapi) and the Finesse API
(https://<server>:8445/finesse/api) use the same login.
"""

from dataclasses import dataclass

from . import ini_store
from .paths import CREDENTIALS_PATH


@dataclass
class UccxConnection:
    name: str
    server: str
    username: str
    password: str


def _section(name: str) -> str:
    return f"UCCX:{name}"


def list_public() -> list[dict[str, str]]:
    """Connections without secrets, safe for the browser."""
    out = []
    for s in ini_store.read_sections(CREDENTIALS_PATH):
        if s["service"] != "UCCX" or s["identifier"] == "default":
            continue
        f = s["fields"]
        out.append({
            "name": s["identifier"],
            "server": f.get("server", ""),
            "username": f.get("username", ""),
            "org": f.get("org", ""),
            "has_password": "yes" if s["secrets"].get("password") else "no",
        })
    return out


def load(name: str) -> UccxConnection | None:
    kv = ini_store.read_section(CREDENTIALS_PATH, _section(name))
    if not kv.get("server"):
        return None
    return UccxConnection(
        name=name,
        server=kv.get("server", ""),
        username=kv.get("username", ""),
        password=kv.get("password", ""),
    )


def save(name: str, server: str, username: str, password: str | None, org: str | None = None) -> None:
    """password None/'' keeps the stored one."""
    old = load(name)
    values: dict[str, str | None] = {"server": server, "username": username}
    if org is not None:
        values["org"] = org
    if password:
        values["password"] = password
    elif old is None:
        values["password"] = ""
    ini_store.upsert_section(CREDENTIALS_PATH, _section(name), values)


def delete(name: str) -> bool:
    return ini_store.delete_section(CREDENTIALS_PATH, _section(name))
