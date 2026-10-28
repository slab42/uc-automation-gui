import reflex as rx

from ..components.crud_page import (
    Column, CrudPageConfig, build_crud_page, dependency_dialogs, dependency_toolbar, form_field, text_input,
)
from ..state.system import CodecListsState, DevicePoolsState, LocationsState, RegionsState


def _hint(text: str) -> rx.Component:
    return rx.text(text, size="1", color="var(--gray-10)")


def _deps(title: str, header: str, text: str) -> dict:
    return dict(
        extra_toolbar=dependency_toolbar,
        extra_dialogs=lambda S, h: dependency_dialogs(S, h, title, header, text),
    )


# --- Audio codec preference lists ---

def _codec_form(S) -> rx.Component:
    return rx.vstack(
        form_field("Name", text_input(S, "name", "Standard-G711")),
        form_field("Description", text_input(S, "description")),
        form_field("Codecs, in priority order", text_input(S, "codecs", "G.711 ulaw 64k;G.729")),
        _hint("Separate codecs with a semicolon. The first codec has the highest priority. Use the codec "
              "names CUCM shows, for example G.711 ulaw 64k, G.711 alaw 64k, G.722, G.729, iLBC."),
        spacing="3", align="start", width="100%",
    )


codec_lists = build_crud_page(CodecListsState, CrudPageConfig(
    title="Audio Codec Preference Lists", noun="audio codec preference list", key="name",
    columns=[Column("Name", "name", code=True), Column("Description", "description"),
             Column("Codecs (in order)", "codecs")],
    add_body=_codec_form,
    import_notes=("codecs lists the codecs in priority order, separated by semicolons, and is required to add. "
                  "In Modify, a codecs value replaces the whole list."),
    can_copy=True,
))


# --- Regions ---

def _region_form(S) -> rx.Component:
    return rx.vstack(
        form_field("Name", text_input(S, "name", "REG-HQ")),
        form_field("Default codec", text_input(S, "defaultCodec")),
        _hint("Leave the default codec blank to use CUCM's default. System regions (Default) are not listed."),
        spacing="3", align="start", width="100%",
    )


regions = build_crud_page(RegionsState, CrudPageConfig(
    title="Regions", noun="region", key="name",
    columns=[Column("Name", "name", code=True), Column("Default codec", "defaultCodec")],
    add_body=_region_form,
    import_notes="Only name is required. The default codec cannot be changed after the region is added.",
    can_modify=False,
    delete_note="Check dependencies first: regions used by device pools or devices cannot be removed.",
    **_deps("Region dependencies", "Region", "Checking device pools, devices, trunks and media resources..."),
))


# --- Locations ---

def _location_form(S) -> rx.Component:
    return rx.vstack(
        form_field("Name", text_input(S, "name", "LOC-HQ")),
        rx.grid(
            form_field("Audio bandwidth within the location (kbps)", text_input(S, "withinAudioBandwidth", type="number")),
            form_field("Video bandwidth within the location (kbps)", text_input(S, "withinVideoBandwidth", type="number")),
            columns="2", spacing="3", width="100%",
        ),
        _hint("-1 is unlimited. A new location is linked to Hub_None. System locations (Phantom, Shadow, "
              "Hub_None) are not listed."),
        spacing="3", align="start", width="100%",
    )


locations = build_crud_page(LocationsState, CrudPageConfig(
    title="Locations", noun="location", key="name",
    columns=[Column("Name", "name", code=True), Column("Audio kbps", "withinAudioBandwidth"),
             Column("Video kbps", "withinVideoBandwidth")],
    add_body=_location_form,
    import_notes="Modify changes the two bandwidth columns that are filled in.",
    delete_note="Check dependencies first: locations used by device pools or devices cannot be removed.",
    **_deps("Location dependencies", "Location", "Checking device pools, devices, trunks and media resources..."),
))


# --- Device pools ---

def _device_pool_form(S) -> rx.Component:
    return rx.vstack(
        form_field("Name", text_input(S, "name", "DP-HQ")),
        rx.grid(
            form_field("Region", text_input(S, "regionName")),
            form_field("Location", text_input(S, "locationName")),
            form_field("Call Manager group", text_input(S, "callManagerGroupName")),
            form_field("Date/time group", text_input(S, "dateTimeSettingName")),
            form_field("SRST reference", text_input(S, "srstName")),
            columns="2", spacing="3", width="100%",
        ),
        _hint("Names must match existing CUCM objects. Other device pool settings are left at CUCM defaults."),
        spacing="3", align="start", width="100%",
    )


device_pools = build_crud_page(DevicePoolsState, CrudPageConfig(
    title="Device Pools", noun="device pool", key="name",
    columns=[Column("Name", "name", code=True), Column("Region", "regionName"), Column("Location", "locationName"),
             Column("CM group", "callManagerGroupName"), Column("Date/time", "dateTimeSettingName"),
             Column("SRST", "srstName")],
    add_body=_device_pool_form,
    import_notes="Only name is required. Add uses CUCM defaults for blank cells; Modify changes filled-in columns.",
    delete_note="Check dependencies first: device pools with devices, profiles or route group gateways cannot be removed.",
    can_copy=True,
    **_deps("Device pool dependencies", "Device pool",
            "Checking devices, device profiles, remote destination profiles and route groups. This can take a while..."),
))
