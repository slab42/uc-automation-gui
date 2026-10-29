"""Saved CUC connections, stored as [CUC:<name>] sections in .env/credentials.env.

Keys: server, username, password, version (detected CUC major release),
schema_version (REST schema folder used for that release).
"""

from dataclasses import dataclass

from . import ini_store
from .paths import CREDENTIALS_PATH


@dataclass
class CucConnection:
    name: str
    server: str
    username: str
    password: str
    version: str = ""
    schema_version: str = ""


def _section(name: str) -> str:
    return f"CUC:{name}"


def list_public() -> list[dict[str, str]]:
    """Connections without secrets, safe for the browser."""
    out = []
    for s in ini_store.read_sections(CREDENTIALS_PATH):
        if s["service"] != "CUC" or s["identifier"] == "default":
            continue
        f = s["fields"]
        out.append({
            "name": s["identifier"],
            "server": f.get("server", ""),
            "username": f.get("username", ""),
            "version": f.get("version", ""),
            "schema_version": f.get("schema_version", ""),
            "has_password": "yes" if s["secrets"].get("password") else "no",
        })
    return out


def load(name: str) -> CucConnection | None:
    kv = ini_store.read_section(CREDENTIALS_PATH, _section(name))
    if not kv.get("server"):
        return None
    return CucConnection(
        name=name,
        server=kv.get("server", ""),
        username=kv.get("username", ""),
        password=kv.get("password", ""),
        version=kv.get("version", ""),
        schema_version=kv.get("schema_version", ""),
    )


def save(name: str, server: str, username: str, password: str | None,
         version: str | None = None, schema_version: str | None = None) -> None:
    """password None/'' keeps the stored one. Changing server/username clears stale version info."""
    old = load(name)
    values: dict[str, str | None] = {"server": server, "username": username}
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
