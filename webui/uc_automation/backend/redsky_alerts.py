"""RedSky Alerts: Add Alerts (subscriptions) and Check All Buildings."""

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
    slug="alerts-add", title="Add Alerts", noun="alert subscription",
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


def _check_all_buildings(client: RedskyClient) -> tuple[int, list[dict[str, str]]]:
    """Buildings without an alert named like the Building that has the Building as a subscribed location."""
    buildings = client.list_buildings()
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
    slug="alerts-check", title="Check All Buildings", noun="building",
    blurb="Check that every Building has an alert named exactly like the Building (Building Foxden needs an alert "
          "named Foxden) with that Building in its subscribed locations. Names are matched case-insensitively. If "
          "several alerts share the name, the Building passes when any one of them includes it.",
    columns=(("building", "Building"), ("buildingId", "Building ID"), ("issue", "Issue")),
    run=_check_all_buildings,
    ok_message="Every building has a matching alert.",
)
