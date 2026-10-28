"""Composite row keys for objects identified by several fields (pattern + partition)."""

KEY_SEP = "|"


def split_key(key: str, parts: int = 2) -> list[str]:
    return (key.split(KEY_SEP) + [""] * parts)[:parts]
