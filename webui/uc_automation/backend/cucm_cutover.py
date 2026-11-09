"""Webex Cutover (CUCM): the three cutover steps for a list of DNs.

1) remove the enterprise and E.164 alternate numbers, 2) move the DN to another route partition, 3) add the
Advertised Pattern and Route Pattern on the SME cluster (the SME Adv & Route Patterns tool). Steps 1 and 2 reuse
`cucm_dn`, step 3 reuses `cucm_sme_patterns`. The step 3 settings are those of the SME page.
"""

import csv
import io

from .cucm_axl import AxlError
from .cucm_connections import CucmConnection
from .cucm_dn import move_dn, remove_alt_numbers
from .cucm_sme_patterns import add_pattern_pair
from .keys import KEY_SEP
from .paste import paste_to_csv

DN_COLUMNS = ("dn", "partition")
_MARKERS = ("dn", "pattern", "partition", "routepartitionname")


def parse_dn_list(text: str, default_partition: str) -> list[dict[str, str]]:
    """Rows {dn, partition} from pasted text or CSV text (dn first, optional partition second, header optional).
    A blank partition takes `default_partition`. Repeated DN and partition pairs are kept once."""
    data = paste_to_csv(text, columns=DN_COLUMNS, markers=_MARKERS)
    rows = list(csv.reader(io.StringIO(data.decode("utf-8"))))
    header = [c.strip().lower() for c in rows[0]]
    d = next((i for i, h in enumerate(header) if h in ("dn", "pattern")), 0)
    p = next((i for i, h in enumerate(header) if h in ("partition", "routepartitionname")), -1)
    out, seen = [], set()
    for r in rows[1:]:
        dn = r[d].strip() if d < len(r) else ""
        if not dn:
            continue
        part = (r[p].strip() if 0 <= p < len(r) else "") or default_partition.strip()
        if (dn, part) not in seen:
            seen.add((dn, part))
            out.append({"dn": dn, "partition": part})
    return out


def label(row: dict[str, str]) -> str:
    return f"{row['dn']} ({row['partition']})" if row["partition"] else row["dn"]


def remove_alt(conn: CucmConnection, row: dict[str, str]) -> str:
    """A DN that starts with + is tried again as \\+... when CUCM does not find it."""
    dn = row["dn"]
    try:
        return remove_alt_numbers(conn, f"{dn}{KEY_SEP}{row['partition']}")
    except AxlError as e:
        if not dn.startswith("+") or "not found" not in str(e).lower():
            raise
    alt = "\\" + dn
    done = remove_alt_numbers(conn, alt + KEY_SEP + row["partition"])
    return f"{done} (found as {alt})"


def move_partition(conn: CucmConnection, row: dict[str, str], new_partition: str) -> str:
    move_dn(conn, f"{row['dn']}{KEY_SEP}{row['partition']}", new_partition.strip())
    return f"Moved to {new_partition.strip()}"


def add_sme_patterns(sme_conn: CucmConnection, settings: dict[str, str], names: list[str], row: dict[str, str],
                     values: list[str], adv_anyway: bool = False) -> str:
    return add_pattern_pair(sme_conn, settings, names, row["dn"], values, adv_anyway)

