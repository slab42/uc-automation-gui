"""Named sets of router credentials, stored as [CUBE:<name>] sections in .env/credentials.env.

Keys: username, password. A set is not tied to one router, so many routers can share it.
The CLI reads [CUBE:<hostname>] first and falls back to [CUBE:default].
"""

from dataclasses import dataclass

from . import ini_store
from .paths import CREDENTIALS_PATH


@dataclass
class CubeCredential:
    name: str
    username: str
    password: str


def _section(name: str) -> str:
    return f"CUBE:{name}"


def list_public() -> list[dict[str, str]]:
    """Credential sets without secrets, safe for the browser."""
    out = []
    for s in ini_store.read_sections(CREDENTIALS_PATH):
        if s["service"] != "CUBE":
            continue
        out.append({
            "name": s["identifier"],
            "username": s["fields"].get("username", ""),
            "has_password": "yes" if s["secrets"].get("password") else "no",
        })
    return out


def load(name: str) -> CubeCredential | None:
    kv = ini_store.read_section(CREDENTIALS_PATH, _section(name))
    if not kv.get("username"):
        return None
    return CubeCredential(name=name, username=kv.get("username", ""), password=kv.get("password", ""))


def save(name: str, username: str, password: str | None) -> None:
    """password None/'' keeps the stored one."""
    values: dict[str, str | None] = {"username": username}
    if password:
        values["password"] = password
    elif load(name) is None:
        values["password"] = ""
    ini_store.upsert_section(CREDENTIALS_PATH, _section(name), values)


def delete(name: str) -> bool:
    return ini_store.delete_section(CREDENTIALS_PATH, _section(name))
