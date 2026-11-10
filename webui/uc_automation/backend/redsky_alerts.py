"""RedSky Alerts: Add-Edit Alerts (subscriptions) and Check Buildings."""

from .redsky_api import RedskyClient, RedskyError
from .redsky_common import (AddSpec, CheckSpec, Field, location_map, normalize, parse_bool, resolve_location,
                            split_list)

NO_ALERT = "No alert with this name"
NOT_SUBSCRIBED = "Alert exists but Building is not a subscribed location"


def _template_type(template: dict) -> str:
    alert_type = template.get("alertType") or template.get("alertTypeTO") or {}
    return alert_type.get("name", "") if isinstance(alert_type, dict) else str(alert_type)


def _prepare(client: RedskyClient) -> dict:
    templates, _note = client.list_alert_templates()
    return {
        "alert_types": client.list_alert_types(),
        "templates": templates,
        "building_ids": {b.get("name", "").strip().lower(): b["id"] for b in client.list_buildings()},
        "locations": location_map(client),
    }


def _lookups(client: RedskyClient) -> dict[str, list[str]]:
    templates, _note = client.list_alert_templates()
    return {
        "alert_types": sorted(client.list_alert_types()),
        "templates": sorted({t.get("name", "") for t in templates if t.get("name")}),
    }


def _resolve_type(alert_types: dict[str, str], text: str) -> tuple[str, str]:
    for name, display in alert_types.items():
        if text.lower() in (name.lower(), display.lower()):
            return name, display
    raise RedskyError(f"unknown alert type: '{text}'")


def _resolve_template(templates: list[dict], type_name: str, text: str) -> str:
    for t in templates:
        if t.get("name", "").strip().lower() == text.lower() and _template_type(t) in ("", type_name):
            return t["id"]
    raise RedskyError(f"unknown template for {type_name}: '{text}'")


def _resolve_scope(entries: list[str], ctx: dict) -> list[tuple[str, str]]:
    """A scope entry is a Building name, or a Location ('Building / Location' when the name repeats)."""
    filters = []
    for entry in entries:
        if "/" not in entry and entry.lower() in ctx["building_ids"]:
            filters.append((ctx["building_ids"][entry.lower()], "BUILDING"))
            continue
        try:
            filters.append((resolve_location(ctx["locations"], entry), "LOCATION"))
        except RedskyError as e:
            raise RedskyError(f"scope entry '{entry}' is not a known building, or {e}")
    return filters


def _add_alert(client: RedskyClient, ctx: dict, row: dict[str, str]) -> str:
    type_pair = _resolve_type(ctx["alert_types"], row["alertType"])
    template_id = _resolve_template(ctx["templates"], type_pair[0], row["template"]) if row["template"] else None
    filters = _resolve_scope(split_list(row["scope"]), ctx) if row["scope"] else []
    new_id, detail = client.add_alert_subscription(
        row["name"], type_pair, template_id, split_list(row["emailRecipients"]), split_list(row["smsRecipients"]),
        row["timezone"], bool(parse_bool(row["allCorporateLocations"])), bool(parse_bool(row["allPersonalLocations"])))
    if filters:
        if not new_id:
            raise RedskyError("Created, but RedSky did not return its id so the scope was not set")
        try:
            client.set_alert_subscription_filters(new_id, filters)
        except RedskyError as e:
            raise RedskyError(f"Subscription created but its scope failed. Correct it in RedSky. {e}")
    return detail


ALERTS_ADD = AddSpec(
    slug="alerts-add", title="Add-Edit Alerts", noun="alert subscription",
    blurb="Add alert subscriptions: who is notified (email and SMS) when an alert type such as an emergency call "
          "occurs, and optionally which Buildings or Locations it covers.",
    fields=(
        Field("name", "Subscription name", required=True),
        Field("alertType", "Alert type", "Machine name or display text, e.g. EMERGENCY_CALL.", required=True,
              options="alert_types"),
        Field("template", "Template", "Optional. Matched by name.", options="templates"),
        Field("emailRecipients", "Email recipients", "Separate several with semicolons."),
        Field("smsRecipients", "SMS recipients", "Separate several with semicolons."),
        Field("timezone", "Timezone", "Optional, e.g. America/Chicago."),
        Field("allCorporateLocations", "All corporate locations", yesno=True, default="No"),
        Field("allPersonalLocations", "All personal locations", yesno=True, default="No"),
        Field("scope", "Scope", "Optional. Buildings and Locations, separated by semicolons. "
                                "Use 'Building / Location' if a location name repeats."),
    ),
    add=_add_alert, prepare=_prepare, lookups=_lookups, label_keys=("name",),
    csv_note="Only name and alertType are required. Separate several recipients or scope entries with semicolons. "
             "The two 'all' columns accept yes/no/true/false/1/0. Use a tab or | between columns when pasting "
             "text with semicolons.",
    example="name,alertType,template,emailRecipients,smsRecipients,timezone,allCorporateLocations,"
            "allPersonalLocations,scope\n"
            "HQ 911 Calls,EMERGENCY_CALL,Default Email,a@example.com;b@example.com,+12175550100,"
            "America/Chicago,no,no,HQ Building;Branch Office\n",
)


def _check_all_buildings(client: RedskyClient, text: str = "") -> tuple[int, list[dict[str, str]]]:
    """Buildings without an alert named like the Building that has the Building as a subscribed location."""
    buildings = client.list_buildings()
    text = text.strip().lower()
    if text:  # only Buildings whose name contains the text are checked and reported
        buildings = [b for b in buildings if text in b.get("name", "").lower()]
    by_name: dict[str, list[dict]] = {}
    for sub in client.list_alert_subscriptions():
        by_name.setdefault(normalize(sub.get("name", "")), []).append(sub)
    scoped: dict[str, set] = {}
    missing = []
    for building in buildings:
        name = building.get("name", "").strip()
        matches = by_name.get(normalize(name), [])
        if not matches:
            missing.append({"building": name, "buildingId": building["id"], "issue": NO_ALERT})
            continue
        subscribed = False
        for sub in matches:
            if sub["id"] not in scoped:
                scoped[sub["id"]] = {f.get("ouId") for f in client.list_alert_subscription_filters(sub["id"])}
            if building["id"] in scoped[sub["id"]]:
                subscribed = True
                break
        if not subscribed:
            missing.append({"building": name, "buildingId": building["id"], "issue": NOT_SUBSCRIBED})
    return len(buildings), missing


ALERTS_CHECK = CheckSpec(
    slug="alerts-check", title="Check Buildings", noun="building",
    blurb="Click a Building name in the results to open Add-Edit Alerts with that Building filled in. Check that every Building has an alert named exactly like the Building (Building Foxden needs an alert "
          "named Foxden) with that Building in its subscribed locations. Names are matched case-insensitively. If "
          "several alerts share the name, the Building passes when any one of them includes it.",
    columns=(("building", "Building"), ("buildingId", "Building ID"), ("issue", "Issue")),
    run=_check_all_buildings,
    ok_message="Every building has a matching alert.",
    input_label="Building Name Contains",
    input_optional=True,
    input_hint="Optional. Only Buildings whose name contains this text (any case) are checked and reported. "
               "Leave empty to check every Building.",
    input_placeholder="Foxden",
)


# --- edit ---

def search_alerts(client: RedskyClient, text: str) -> list[dict[str, str]]:
    """Alert subscriptions whose name contains `text` (any case); every alert when the text is empty."""
    text = text.strip().lower()
    return [{"id": s["id"], "name": s.get("name", ""),
             "alertType": (s.get("alertTypeTO") or {}).get("text") or (s.get("alertTypeTO") or {}).get("name", "")}
            for s in client.list_alert_subscriptions() if text in s.get("name", "").lower()]


def _scope_names(client: RedskyClient, need_locations: bool) -> tuple[dict[str, str], dict[str, str]]:
    """({building id: name}, {location id: 'Building / Location' or name}). Locations are one request per Building,
    so they are read only when needed."""
    buildings = {b["id"]: b.get("name", "").strip() for b in client.list_buildings()}
    locations = {}
    if need_locations:
        locations = {loc["id"]: (f"{b.strip()} / {loc.get('name', '').strip()}" if b else loc.get("name", "").strip())
                     for b, loc in client.list_all_locations()}
    return buildings, locations


def load_alert(client: RedskyClient, alert_id: str) -> tuple[dict[str, str], list[str]]:
    """The alert as an Add-Edit form row (same keys as ALERTS_ADD fields) and a list of warnings."""
    sub = client.get_alert_subscription(alert_id)
    filters = client.list_alert_subscription_filters(alert_id)
    buildings, locations = _scope_names(client, any(f.get("filterType") != "BUILDING" for f in filters))
    scope, warnings = [], []
    for f in filters:
        ou = f.get("ouId")
        name = buildings.get(ou) if f.get("filterType") == "BUILDING" else locations.get(ou)
        if name:
            scope.append(name)
        else:
            warnings.append(f"A scope entry ({f.get('filterType', '?')} {ou}) is not a known Building or Location. "
                            "It is kept unchanged when you save.")
    alert_type = sub.get("alertTypeTO") or {}
    template = (sub.get("alertTemplate") or {}).get("name", "")
    yn = lambda v: "Yes" if v else "No"
    row = {
        "name": sub.get("name", ""),
        "alertType": alert_type.get("name", ""),
        "template": template,
        "emailRecipients": ";".join(r.get("email", "") for r in sub.get("emailRecipients") or []),
        "smsRecipients": ";".join(r.get("phoneNumber", "") for r in sub.get("smsRecipients") or []),
        "timezone": sub.get("timezone") or "",
        "allCorporateLocations": yn(sub.get("allCorporateLocations")),
        "allPersonalLocations": yn(sub.get("allPersonalLocations")),
        "scope": ";".join(scope),
    }
    if sub.get("userRecipients"):
        warnings.append(f"{len(sub['userRecipients'])} user recipient(s) are not shown here. They are kept unchanged.")
    if sub.get("informacastRecipients"):
        warnings.append(f"{len(sub['informacastRecipients'])} Informacast recipient(s) are not shown here. "
                        "They are kept unchanged.")
    return row, warnings


def save_alert(client: RedskyClient, alert_id: str, row: dict[str, str]) -> str:
    """Write the edited row back: PUT the subscription, then replace its scope when it changed."""
    if not row["name"].strip():
        raise RedskyError("The alert needs a name.")
    existing = client.list_alert_subscription_filters(alert_id)
    entries = split_list(row["scope"])
    buildings = {b.get("name", "").strip().lower(): b["id"] for b in client.list_buildings()}
    templates, _note = client.list_alert_templates()
    ctx = {"alert_types": client.list_alert_types(), "templates": templates, "building_ids": buildings, "locations": {}}
    if any(f.get("filterType") != "BUILDING" for f in existing) or any(
            "/" in e or e.lower() not in buildings for e in entries):
        ctx["locations"] = location_map(client)
    type_pair = _resolve_type(ctx["alert_types"], row["alertType"])
    template_id = _resolve_template(ctx["templates"], type_pair[0], row["template"]) if row["template"] else None
    wanted = _resolve_scope(entries, ctx) if entries else []
    current = client.get_alert_subscription(alert_id)
    payload = {
        "id": alert_id, "name": row["name"].strip(),
        "alertTypeTO": {"name": type_pair[0], "text": type_pair[1]},
        "emailRecipients": [{"email": e} for e in split_list(row["emailRecipients"])],
        "smsRecipients": [{"phoneNumber": n} for n in split_list(row["smsRecipients"])],
        "userRecipients": current.get("userRecipients") or [],
        "informacastRecipients": [r["id"] for r in current.get("informacastRecipients") or [] if r.get("id")],
        "allCorporateLocations": bool(parse_bool(row["allCorporateLocations"])),
        "allPersonalLocations": bool(parse_bool(row["allPersonalLocations"])),
    }
    if template_id:
        payload["templateId"] = template_id
    if row["timezone"].strip():
        payload["timezone"] = row["timezone"].strip()
    client.update_alert_subscription(payload)
    # Scope: entries the Building and Location lists do not know are kept as they are.
    known = {b for b in ctx["building_ids"].values()} | {i for i in ctx["locations"].values() if i}
    keep = [(f["ouId"], f.get("filterType", "")) for f in existing if f.get("ouId") not in known]
    old = {(f["ouId"], f.get("filterType", "")) for f in existing if f.get("ouId") in known}
    if old != set(wanted):
        try:
            if existing:
                client.delete_alert_subscription_filters(alert_id)
            if wanted or keep:
                client.set_alert_subscription_filters(alert_id, wanted + keep)
        except RedskyError as e:
            raise RedskyError(f"Alert saved but its scope failed. Check it in RedSky. {e}")
    return f"Saved {row['name'].strip()}"
