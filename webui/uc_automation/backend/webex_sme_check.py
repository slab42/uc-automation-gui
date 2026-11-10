"""Webex report: SME Pattern Check.

Reads the phone numbers of the Webex org (GET /telephony/config/numbers) and checks each one on the SME cluster for
the Advertised Pattern and the Route Pattern that Webex Cutover (CUCM) would add. The pattern forms and the Route
Pattern partition are those of Webex Cutover (`cucm_sme_patterns.format_advertised_pattern`, `format_route_pattern`,
setting `rp_partition`). The SME patterns are read once (all Advertised Patterns, all Route Patterns of that
partition) and compared in memory. Not tested against a real org or CUCM.
"""

import csv
import io
import re

from .cucm_axl import list_paged
from .cucm_connections import CucmConnection
from .errors import UserError
from .cucm_sme_patterns import format_advertised_pattern, format_route_pattern, require_sme
from .webex_api import WebexClient

PAGE = 2000
STATUS_ALL = "Both Found"
STATUS_ADV = "Advertised Missing"
STATUS_RP = "Route Pattern Missing"
STATUS_NONE = "Both Missing"
ANY_MISSING = "Any Missing"
STATUSES = [STATUS_ALL, STATUS_ADV, STATUS_RP, STATUS_NONE]


def list_webex_numbers(c: WebexClient, progress=lambda text: None) -> list[dict[str, str]]:
    """Every phone number of the org (extension-only entries are skipped): number, location, owner, owner type."""
    out: list[dict[str, str]] = []
    start = 0
    while True:
        page = c.call("GET", "/telephony/config/numbers", {"max": PAGE, "start": start}).get("phoneNumbers") or []
        for r in page:
            number = (r.get("phoneNumber") or "").strip()
            if number:
                owner = r.get("owner") or {}
                name = " ".join(x for x in (owner.get("firstName"), owner.get("lastName")) if x) or owner.get("name", "")
                out.append({"number": number, "location": (r.get("location") or {}).get("name", ""),
                            "owner": name, "owner_type": owner.get("type", ""),
                            "extension": r.get("extension") or ""})
        progress(f"Read {len(out)} number(s)")
        if len(page) < PAGE:
            break
        start += PAGE
    return sorted(out, key=lambda r: r["number"])


def _norm(pattern: str) -> str:
    return pattern.replace("\\", "").strip()


def check_numbers(sme: CucmConnection, partition: str, numbers: list[dict[str, str]],
                  progress=lambda text: None) -> list[dict[str, str]]:
    """One row per number with the Advertised Pattern and Route Pattern it should have, whether each exists on the
    SME cluster, the descriptions found, and a Status."""
    require_sme(sme)
    partition = partition.strip()
    progress("Reading Advertised Patterns from the SME cluster")
    adv = {_norm(r["pattern"]): r for r in list_paged(sme, "listAdvertisedPatterns", "advertisedPatterns",
                                                      {"pattern": "%"}, ["pattern", "description"])}
    progress(f"Reading Route Patterns in {partition} from the SME cluster")
    rps = {_norm(r["pattern"]): r for r in list_paged(
        sme, "listRoutePattern", "routePattern", {"pattern": "%", "routePartitionName": partition},
        ["pattern", "routePartitionName", "description"])}
    rows = []
    for n in numbers:
        adv_p, rp_p = format_advertised_pattern(n["number"]), format_route_pattern(n["number"])
        a, r = adv.get(_norm(adv_p)), rps.get(_norm(rp_p))
        status = STATUS_ALL if a and r else STATUS_ADV if r else STATUS_RP if a else STATUS_NONE
        rows.append({**n, "adv_pattern": adv_p, "adv_found": "Yes" if a else "No",
                     "adv_desc": a["description"] if a else "", "rp_pattern": rp_p,
                     "rp_found": "Yes" if r else "No", "rp_desc": r["description"] if r else "", "status": status})
    return rows


def report_csv(rows: list[dict[str, str]], partition: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Number", "Extension", "Location", "Owner", "Owner Type", "Advertised Pattern", "Advertised Found",
                "Advertised Description", "Route Pattern", f"Route Pattern Found ({partition})",
                "Route Pattern Description", "Status"])
    for r in rows:
        w.writerow([r["number"], r["extension"], r["location"], r["owner"], r["owner_type"], r["adv_pattern"],
                    r["adv_found"], r["adv_desc"], r["rp_pattern"], r["rp_found"], r["rp_desc"], r["status"]])
    return buf.getvalue()


SOURCES = ["Location", "Owner"]


def check_value_regexes(values: list[str]) -> str:
    """Error text for the first value that is not a valid regex, or ''."""
    for v in values:
        if v.strip():
            try:
                re.compile(v.strip())
            except re.error as e:
                return f"Variable regex '{v.strip()}': {e}"
    return ""


def values_from_row(patterns: list[str], row: dict[str, str], source: str) -> list[str]:
    """Variable values for one row: each regex is searched in the row's Location or Owner text and the first capture
    group (else the whole match) is the value. A blank regex gives a blank value. Raises UserError when one does not
    match."""
    text = row["location"] if source == "Location" else row["owner"]
    out = []
    for p in patterns:
        p = p.strip()
        if not p:
            out.append("")
            continue
        m = re.search(p, text)
        if not m:
            raise UserError(f"Regex '{p}' does not match the {source.lower()} '{text}'.")
        out.append((m.group(1) if m.re.groups else m.group(0)).strip())
    return out
