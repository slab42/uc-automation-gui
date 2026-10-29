"""CUC users and mailboxes: extension list parsing, status and usage rows, empty mailbox scan and clean up."""

import csv
import io
from concurrent.futures import ThreadPoolExecutor

from .cuc_api import CucClient, CucError

MB = 1024 * 1024
MAX_WORKERS = 10
STATUS_COLUMNS = [
    ("dtmfAccessId", "Extension"), ("alias", "Alias"), ("displayName", "Display name"), ("sizeMb", "Size MB"),
    ("warningQuotaMb", "Warning MB"), ("receiveQuotaMb", "Receive MB"), ("sendQuotaMb", "Send MB"),
    ("primary", "Primary"), ("storeMounted", "Store mounted"), ("mailboxMounted", "Mailbox mounted"),
    ("storeOverflow", "Store overflow"), ("warningExceeded", "Warning exceeded"),
    ("receiveExceeded", "Receive exceeded"), ("sendExceeded", "Send exceeded"),
]


def parse_extensions(data: bytes) -> list[str]:
    """First column of a CSV (or pasted list) as extensions. A first row without a digit is a header."""
    rows = [r for r in csv.reader(io.StringIO(data.decode("utf-8-sig"))) if r and r[0].strip()]
    if rows and not any(ch.isdigit() for ch in rows[0][0]):
        rows = rows[1:]
    seen: dict[str, None] = {}
    for r in rows:
        seen.setdefault(r[0].strip(), None)
    return list(seen)


def _mb(value: str) -> str:
    try:
        n = int(value or 0)
    except ValueError:
        n = 0
    return f"{n / MB:.2f}" if n > 0 else "0.00"


def _flag(mailbox: dict, key: str) -> str:
    return "yes" if (mailbox.get(key, "") or "").lower() == "true" else "no"


def status_row(usage: dict) -> dict[str, str]:
    """Everything check_userMailbox.py prints, as one flat row of strings."""
    m = usage["mailbox"]
    return {
        "objectId": usage.get("objectId", ""), "uri": usage.get("uri", ""),
        "dtmfAccessId": usage["dtmfAccessId"], "alias": usage["alias"], "displayName": usage["displayName"],
        "sizeMb": f"{usage['byteSize'] / MB:.2f}", "byteSize": str(usage["byteSize"]),
        "warningQuotaMb": _mb(m.get("WarningQuota")), "receiveQuotaMb": _mb(m.get("ReceiveQuota")),
        "sendQuotaMb": _mb(m.get("SendQuota")),
        "primary": _flag(m, "IsPrimary"), "storeMounted": _flag(m, "IsStoreMounted"),
        "mailboxMounted": _flag(m, "IsMailboxMounted"), "storeOverflow": _flag(m, "IsStoreOverFlowed"),
        "warningExceeded": _flag(m, "IsWarningQuotaExceeded"), "receiveExceeded": _flag(m, "IsReceiveQuotaExceeded"),
        "sendExceeded": _flag(m, "IsSendQuotaExceeded"),
    }


def all_status(client: CucClient) -> tuple[list[dict[str, str]], list[str]]:
    """(status rows, failure messages) for every user. Mailboxes are read in parallel, one request per user."""
    users = client.list_users()

    def fetch(user):
        try:
            return status_row(client.mailbox_for_user(user)), ""
        except CucError as e:
            return None, f"{user.get('Alias', '?')}: {e}"
        except Exception as e:
            return None, f"{user.get('Alias', '?')}: unexpected error: {e}"

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        fetched = list(pool.map(fetch, users))
    rows = [r for r, _ in fetched if r]
    rows.sort(key=lambda r: (r["alias"].casefold(), r["objectId"]))
    return rows, [e for _, e in fetched if e]


def filter_rows(rows: list[dict[str, str]], text: str, begins: bool) -> list[dict[str, str]]:
    """Rows whose extension, alias or display name begins with / contains the text, case-insensitive."""
    needle = text.strip().casefold()
    if not needle:
        return rows
    match = (lambda v: v.casefold().startswith(needle)) if begins else (lambda v: needle in v.casefold())
    return [r for r in rows if any(match(r[k]) for k in ("dtmfAccessId", "alias", "displayName"))]


def usage_row(usage: dict) -> dict[str, str]:
    return {"dtmfAccessID": usage["dtmfAccessId"], "alias": usage["alias"], "mailboxSize": str(usage["sizeMb"])}


def to_csv(rows: list[dict[str, str]], fields: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def status_csv(rows: list[dict[str, str]]) -> str:
    return to_csv(rows, [k for k, _ in STATUS_COLUMNS])


def usage_csv(rows: list[dict[str, str]]) -> str:
    return to_csv(rows, ["dtmfAccessID", "alias", "mailboxSize"])


def delete_empty(client: CucClient, uri: str) -> str:
    """Deletes the user account that owns an empty mailbox."""
    client.delete_user(uri)
    return "User account deleted"
