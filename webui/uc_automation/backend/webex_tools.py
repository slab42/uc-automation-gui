"""Webex tools: hardware (phone model and MAC) compatibility check.

Ported from webex/ValidatePhoneCompatibility.py (reference only). Checks each model against the org's supported
device list and each MAC with Webex's validateMacs call (a write-scoped API that only validates). Not tested against a
real org.
"""

import csv
import io
import re

from .webex_api import WebexClient, WebexError

MAC_PATTERN = re.compile(r"^[0-9A-Fa-f]{12}$")
MAC_BATCH_SIZE = 50
SUPPORTED_DEVICES = "/telephony/config/supportedDevices"
VALIDATE_MACS = "/telephony/config/devices/actions/validateMacs/invoke"


def normalize_mac(mac: str) -> str:
    """Strip separators and any other non-hex characters, then uppercase."""
    return re.sub(r"[^0-9A-Fa-f]", "", mac).upper()


def parse_phone_csv(data: bytes) -> list[dict[str, str]]:
    """Header row skipped. Columns are model and mac: by header name when both are present, else by position."""
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace"))))
    if not rows:
        raise ValueError("The CSV file is empty.")
    header = [h.strip().lower() for h in rows[0]]
    mi, ai = (header.index("model"), header.index("mac")) if "model" in header and "mac" in header else (0, 1)
    out = []
    for n, r in enumerate(rows[1:], 2):
        model = r[mi].strip() if len(r) > mi else ""
        mac = r[ai].strip() if len(r) > ai else ""
        if model or mac:
            out.append({"row": str(n), "model": model, "mac": mac})
    return out


def get_supported_devices(c: WebexClient) -> dict[str, dict]:
    """The org's supported devices keyed by lowercased model code and display name."""
    devices: dict[str, dict] = {}
    for d in c.call("GET", SUPPORTED_DEVICES).get("devices") or []:
        entry = {"model": d.get("model", ""), "displayName": d.get("displayName", ""),
                 "onboardingMethod": d.get("onboardingMethod") or []}
        for key in (d.get("model"), d.get("displayName")):
            if key:
                devices[key.strip().lower()] = entry
    if not devices:
        raise WebexError("Webex returned no supported devices, so compatibility cannot be checked.")
    return devices


def model_names(devices: dict[str, dict]) -> list[str]:
    return sorted({d["displayName"] or d["model"] for d in devices.values()})


def model_import_rows(devices: dict[str, dict]) -> list[dict[str, str]]:
    """One row per supported model: the text to put in the model column and the display name."""
    seen: dict[str, dict[str, str]] = {}
    for d in devices.values():
        code = d["model"] or d["displayName"]
        seen[code] = {"model": code, "name": d["displayName"] if d["displayName"] != code else ""}
    return [seen[k] for k in sorted(seen, key=str.lower)]


def validate_macs(c: WebexClient, macs: list[str]) -> dict[str, dict[str, str]]:
    """MAC to {state, message}. States: AVAILABLE, UNAVAILABLE (in use), DUPLICATE_IN_LIST, INVALID, UNKNOWN (call failed)."""
    states: dict[str, dict[str, str]] = {}
    for start in range(0, len(macs), MAC_BATCH_SIZE):
        batch = macs[start:start + MAC_BATCH_SIZE]
        try:
            body = c.call("POST", VALIDATE_MACS, body={"macs": batch})
        except WebexError as e:
            for m in batch:
                states[m] = {"state": "UNKNOWN", "message": str(e)}
            continue
        # Webex returns macStatus only for MACs with a problem; the rest of a clean batch are available.
        for m in batch:
            states[m] = {"state": "AVAILABLE", "message": ""}
        for e in body.get("macStatus") or []:
            states[normalize_mac(e.get("mac", ""))] = {"state": e.get("state", "INVALID"),
                                                       "message": e.get("message", "")}
    return states


def validate_row(model: str, mac: str, devices: dict[str, dict], mac_states: dict[str, dict[str, str]]) -> tuple[str, str]:
    """(status, reason): VALID, WARNING or INVALID."""
    if not model or not mac:
        return "INVALID", "Missing model or MAC address"
    nmac = normalize_mac(mac)
    if not MAC_PATTERN.match(nmac):
        return "INVALID", f'MAC address "{mac}" is not a valid 12 hex-digit MAC'
    device = devices.get(model.strip().lower())
    if not device:
        return "INVALID", f'Model "{model}" is not a supported Webex Calling device for this org'
    res = mac_states.get(nmac, {"state": "UNKNOWN", "message": ""})
    state, msg = res["state"], res["message"] or "no further detail"
    if state == "UNAVAILABLE":
        return "INVALID", f'MAC address "{nmac}" is already in use in Webex ({msg})'
    if state == "DUPLICATE_IN_LIST":
        return "INVALID", f'MAC address "{nmac}" is duplicated elsewhere in the list'
    if state == "INVALID":
        return "INVALID", f'Webex rejected MAC address "{nmac}" as invalid ({msg})'
    if state == "UNKNOWN":
        return "WARNING", f'MAC address "{nmac}" could not be validated against Webex ({msg})'
    if device["onboardingMethod"] and "MAC_ADDRESS" not in device["onboardingMethod"]:
        return "WARNING", (f'Model "{model}" does not support MAC address onboarding '
                           f'(supports: {", ".join(device["onboardingMethod"])})')
    return "VALID", f'Model "{model}" is supported ({device["displayName"]}) and MAC "{nmac}" is available in Webex'


def check_phones(c: WebexClient, rows: list[dict[str, str]], devices: dict[str, dict]) -> list[dict[str, str]]:
    """Check every row. All MACs go to Webex in batches first, then each row is judged."""
    candidates = [normalize_mac(r["mac"]) for r in rows if MAC_PATTERN.match(normalize_mac(r["mac"]))]
    states = validate_macs(c, candidates) if candidates else {}
    out = []
    for r in rows:
        status, reason = validate_row(r["model"], r["mac"], devices, states)
        out.append({**r, "status": status, "reason": reason})
    return out


def results_csv(results: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["row", "model", "mac", "status", "reason"])
    for r in results:
        w.writerow([r["row"], r["model"], r["mac"], r["status"], r["reason"]])
    return buf.getvalue()
