"""RedSky Buildings and Locations: Add Buildings, Add Locations, Check Entire Site."""

from .redsky_api import RedskyClient, RedskyError
from .redsky_common import AddSpec, CheckSpec, Field, normalize

SUFFIX = " - Entire Site"


def _add_building(client: RedskyClient, _ctx, row: dict[str, str]) -> str:
    return client.add_building(row["name"], row["fullAddress"], row["supplementalData"])


def _building_ids(client: RedskyClient) -> dict[str, str]:
    return {b.get("name", "").strip().lower(): b["id"] for b in client.list_buildings()}


def _add_location(client: RedskyClient, building_ids: dict[str, str], row: dict[str, str]) -> str:
    if row["building"]:
        parent_id = building_ids.get(row["building"].strip().lower())
        if not parent_id:
            raise RedskyError(f"unknown building: {row['building']}")
    else:
        parent_id = client.org_id
    return client.add_location(
        row["name"], parent_id, fullAddress=row["fullAddress"], info=row["info"], alternateId=row["alternateId"],
        callbackNumber=row["callbackNumber"], htmlLinkUrl=row["htmlLinkUrl"], htmlLinkName=row["htmlLinkName"],
        orgNameOverride=row["orgNameOverride"])


def _building_names(client: RedskyClient) -> dict[str, list[str]]:
    return {"buildings": sorted(b.get("name", "") for b in client.list_buildings() if b.get("name"))}


BUILDINGS_ADD = AddSpec(
    slug="buildings-add", title="Add Buildings", noun="building",
    blurb="Add Buildings to RedSky. RedSky validates every address: an ambiguous or invalid address is not created "
          "and the row fails so it can be corrected and retried.",
    fields=(
        Field("name", "Building name", "Name shown in RedSky.", required=True),
        Field("fullAddress", "Full address", "Street address; RedSky validates and normalizes it.", required=True),
        Field("supplementalData", "Supplemental data", "Optional extra location detail."),
    ),
    add=_add_building,
    csv_note="Quote an address that contains commas, or separate the columns with a tab or | instead.",
    example='name,fullAddress,supplementalData\nHQ Building,"100 Main St, Springfield, IL 62701",Floor 1-5\n',
)

LOCATIONS_ADD = AddSpec(
    slug="locations-add", title="Add Locations", noun="location",
    blurb="Add Locations under a Building. Leave the building blank to place a location directly under the "
          "organization (tenants without a Buildings layer).",
    fields=(
        Field("name", "Location name", "Name shown in RedSky.", required=True),
        Field("building", "Building", "Building name. Blank places the location under the organization.",
              options="buildings"),
        Field("fullAddress", "Full address", "Optional. Blank uses the Building's address."),
        Field("info", "Info"),
        Field("alternateId", "Alternate ID"),
        Field("callbackNumber", "Callback number"),
        Field("htmlLinkUrl", "HTML link URL"),
        Field("htmlLinkName", "HTML link name"),
        Field("orgNameOverride", "Org name override"),
    ),
    add=_add_location, prepare=_building_ids, lookups=_building_names, label_keys=("name",),
    csv_note="Only name is required. A Building that is not found in RedSky fails its row. Quote an address that "
             "contains commas, or separate the columns with a tab or | instead.",
    example="name,building,fullAddress,info,alternateId,callbackNumber,htmlLinkUrl,htmlLinkName,orgNameOverride\n"
            "Room 101,HQ Building,,Floor 1 East,,+12175550100,,,\n",
)


def _check_entire_site(client: RedskyClient) -> tuple[int, list[dict[str, str]]]:
    """Buildings without a '<Building Name> - Entire Site' location."""
    buildings = client.list_buildings()
    missing = []
    for building in buildings:
        name = building.get("name", "").strip()
        expected = f"{name}{SUFFIX}"
        if not any(normalize(loc.get("name", "")) == normalize(expected)
                   for loc in client.list_locations(building["id"])):
            missing.append({"building": name, "buildingId": building["id"], "expectedLocation": expected})
    return len(buildings), missing


ENTIRE_SITE = CheckSpec(
    slug="entire-site", title="Check Entire Site", noun="building",
    blurb='Check that every Building has a location named "<Building Name> - Entire Site". '
          "The name is matched case-insensitively, ignoring extra spaces.",
    columns=(("building", "Building"), ("buildingId", "Building ID"), ("expectedLocation", "Expected location")),
    run=_check_entire_site,
    ok_message='Every building has a "<Building Name> - Entire Site" location.',
)
