import reflex as rx

from .config import APP_NAME, PLATFORMS
from .pages.advertised_patterns import advertised_patterns
from .pages.css import css
from .pages.credentials import credentials, webex_callback
from .pages.cuc_handlers import call_map, delete_handlers, list_handlers
from .pages.cuc_home import cuc_home
from .pages.cuc_users import remove_empty, status_check, usage_check
from .pages.cucm_home import cucm_home
from .pages import redsky_tools as rs_pages
from .pages.cube_tools import config_compare, cube_home, mem_status
from .pages.dn import alternate_numbers, move_partition, orphans
from .pages.devices import (
    cti_route_points,
    common_device_configs,
    mpp_phones,
    phone_button_templates,
    phones,
    softkey_templates,
)
from .pages.home import home
from .pages.hunt_groups import hunt_groups
from .pages.logs import logs
from .pages.partitions import partitions
from .pages.tools import em_bulk_login, phone_count, set_user_pin
from .pages.system import codec_lists, device_pools, locations, regions
from .pages.webex_routing import add_numbers, call_forward, call_queues, hunt_groups as webex_hunt_groups, virtual_lines, webex_home
from .pages.webex_locations import e911, schedules
from .pages.webex_tools import hardware_compatibility
from .pages.webex_users import add_workspace, delete_users, migrate, reset_pin, voicemail
from .pages.pickup_groups import pickup_groups
from .pages.route_patterns import route_patterns
from .pages.translation_patterns import translation_patterns
from .pages.platform import platform_page
from .pages.settings import settings
from .state.advertised_patterns import AdvertisedPatternsState
from .state.css import CssState
from .state.cucm import CucmState
from .state.cuc import CucState
from .state import redsky_tools as rs_state
from .state.cube import CubeState
from .state.cube_tools import ConfigCompareState, MemStatusState
from .state.redsky import RedskyState
from .state.cuc_handlers import ListHandlersState
from .state.cuc_users import RemoveEmptyState, StatusCheckState, UsageCheckState
from .state.dn import AlternateNumbersState, MoveDnState, OrphansState
from .state.devices import (
    CtiRoutePointsState,
    CommonDeviceConfigsState,
    MppPhonesState,
    PhoneButtonTemplatesState,
    PhonesState,
    SoftkeyTemplatesState,
)
from .state.logs import LogsState
from .state.webex import WebexState
from .state.webex_groups import CallQueuesState, HuntGroupsState as WebexHuntGroupsState, VirtualLinesState
from .state.webex_locations import E911State, SchedulesState
from .state.webex_tools import HardwareCompatState
from .state.webex_users import AddWorkspaceState, DeleteUsersState, MigrateState, ResetPinState, VoicemailState
from .state.webex_routing import AddNumbersState, CallForwardState, WebexSession
from .state.hunt_groups import HuntGroupsState
from .state.partitions import PartitionsState
from .state.tools import EmBulkState, PhoneCountState, SetPinState
from .state.system import CodecListsState, DevicePoolsState, LocationsState, RegionsState
from .state.pickup_groups import PickupGroupsState
from .state.route_patterns import RoutePatternsState
from .state.translation_patterns import TranslationPatternsState

app = rx.App(
    head_components=[rx.el.link(rel="icon", href="/slab42.jpg")],
)

app.add_page(home, route="/", title=APP_NAME)
for _p in PLATFORMS:
    if _p.slug in ("cucm", "cuc", "cube", "webex", "redsky"):
        continue
    app.add_page(platform_page(_p), route=f"/{_p.slug}", title=f"{_p.label} | {APP_NAME}")
app.add_page(cube_home, route="/cube", title=f"CUBE | {APP_NAME}")
app.add_page(mem_status, route="/cube/mem-status", title=f"CUBE Mem Status | {APP_NAME}",
             on_load=MemStatusState.load_page)
app.add_page(config_compare, route="/cube/config-compare", title=f"CUBE Config Compare | {APP_NAME}",
             on_load=ConfigCompareState.load_page)
app.add_page(webex_home, route="/webex", title=f"Webex | {APP_NAME}", on_load=WebexSession.on_page_load)
app.add_page(add_numbers, route="/webex/add-numbers", title=f"Add Numbers | {APP_NAME}",
             on_load=AddNumbersState.load_page)
app.add_page(call_forward, route="/webex/call-forward", title=f"Call Forward | {APP_NAME}",
             on_load=CallForwardState.on_page_load)
for _route, _title, _page, _state in [
    ("/webex/call-queues", "Call Queues", call_queues, CallQueuesState),
    ("/webex/hunt-groups", "Webex Hunt Groups", webex_hunt_groups, WebexHuntGroupsState),
    ("/webex/virtual-lines", "Virtual Lines", virtual_lines, VirtualLinesState),
    ("/webex/migrate", "Migrate", migrate, MigrateState),
    ("/webex/schedules", "Schedules", schedules, SchedulesState),
    ("/webex/e911", "E911", e911, E911State),
    ("/webex/hardware-compatibility", "Check Hardware Compatibility", hardware_compatibility, HardwareCompatState),
]:
    app.add_page(_page, route=_route, title=f"{_title} | {APP_NAME}", on_load=_state.load_page)
for _route, _title, _page, _state in [
    ("/webex/delete-users", "Delete Users", delete_users, DeleteUsersState),
    ("/webex/reset-pin", "Reset PIN", reset_pin, ResetPinState),
    ("/webex/add-workspace", "Add Device", add_workspace, AddWorkspaceState),
    ("/webex/voicemail", "Voicemail", voicemail, VoicemailState),
]:
    app.add_page(_page, route=_route, title=f"{_title} | {APP_NAME}",
                 on_load=_state.load_page if _state in (AddWorkspaceState, VoicemailState) else _state.on_page_load)
app.add_page(logs, route="/logs", title=f"Logs | {APP_NAME}", on_load=LogsState.on_page_load)
app.add_page(settings, route="/settings", title=f"Settings | {APP_NAME}")

app.add_page(cuc_home, route="/cuc", title=f"CUC | {APP_NAME}", on_load=CucState.load_connections)
for _route, _title, _page in [
    ("/cuc/map", "Map", call_map),
    ("/cuc/delete-handlers", "Bulk Delete", delete_handlers),
]:
    app.add_page(_page, route=_route, title=f"CUC {_title} | {APP_NAME}", on_load=CucState.load_connections)
for _route, _title, _page, _state in [
    ("/cuc/status-check", "Status Check", status_check, StatusCheckState),
    ("/cuc/usage-check", "Usage Check", usage_check, UsageCheckState),
    ("/cuc/remove-empty", "Remove Empty", remove_empty, RemoveEmptyState),
]:
    app.add_page(_page, route=_route, title=f"CUC {_title} | {APP_NAME}",
                 on_load=[CucState.load_connections, _state.auto_load])
app.add_page(list_handlers, route="/cuc/list-handlers", title=f"CUC Search | {APP_NAME}",
             on_load=[CucState.load_connections, ListHandlersState.auto_load])
app.add_page(rs_pages.redsky_home, route="/redsky", title=f"RedSky | {APP_NAME}", on_load=RedskyState.load_connections)
for _route, _title, _page, _state in [
    ("/redsky/buildings-add", "Add Buildings", rs_pages.buildings_add, rs_state.AddBuildingsState),
    ("/redsky/locations-add", "Add Locations", rs_pages.locations_add, rs_state.AddLocationsState),
    ("/redsky/alerts-add", "Add Alerts", rs_pages.alerts_add, rs_state.AddAlertsState),
    ("/redsky/bssid", "BSSID", rs_pages.bssid, rs_state.BssidState),
    ("/redsky/lldp", "LLDP", rs_pages.lldp, rs_state.LldpState),
    ("/redsky/private-ip", "Private IP", rs_pages.private_ip, rs_state.PrivateIpState),
    ("/redsky/public-ip", "Public IP", rs_pages.public_ip, rs_state.PublicIpState),
]:
    app.add_page(_page, route=_route, title=f"RedSky {_title} | {APP_NAME}",
                 on_load=[RedskyState.load_connections, _state.load_lookups])
for _route, _title, _page in [
    ("/redsky/entire-site", "Check Entire Site", rs_pages.entire_site),
    ("/redsky/alerts-check", "Check All Buildings", rs_pages.alerts_check),
]:
    app.add_page(_page, route=_route, title=f"RedSky {_title} | {APP_NAME}", on_load=RedskyState.load_connections)
app.add_page(cucm_home, route="/cucm", title=f"CUCM | {APP_NAME}", on_load=CucmState.load_connections)
app.add_page(
    advertised_patterns,
    route="/cucm/advertised-patterns",
    title=f"Advertised Patterns | {APP_NAME}",
    on_load=AdvertisedPatternsState.on_page_load,
)
app.add_page(
    credentials,
    route="/credentials",
    title=f"Credentials | {APP_NAME}",
    on_load=[CucmState.load_connections, CucState.load_connections, RedskyState.load_connections,
             CubeState.load_credentials,
             WebexState.on_credentials_load],
)
app.add_page(webex_callback, route="/webex/callback", title=f"Webex login | {APP_NAME}",
             on_load=WebexState.handle_callback)
app.add_page(
    partitions,
    route="/cucm/partitions",
    title=f"Partitions | {APP_NAME}",
    on_load=PartitionsState.on_page_load,
)
app.add_page(
    css,
    route="/cucm/calling-search-spaces",
    title=f"Calling Search Spaces | {APP_NAME}",
    on_load=CssState.on_page_load,
)

app.add_page(
    pickup_groups,
    route="/cucm/call-pickup-groups",
    title=f"Call Pickup Groups | {APP_NAME}",
    on_load=PickupGroupsState.on_page_load,
)

for _route, _title, _page, _state in [
    ("/cucm/audio-codec-preference-lists", "Audio Codec Preference Lists", codec_lists, CodecListsState),
    ("/cucm/device-pools", "Device Pools", device_pools, DevicePoolsState),
    ("/cucm/locations", "Locations", locations, LocationsState),
    ("/cucm/regions", "Regions", regions, RegionsState),
    ("/cucm/dn-move-partition", "Move Partition", move_partition, MoveDnState),
    ("/cucm/dn-alternate-numbers", "Alternate Numbers", alternate_numbers, AlternateNumbersState),
    ("/cucm/dn-orphans", "Orphan Directory Numbers", orphans, OrphansState),
    ("/cucm/phones", "Phones", phones, PhonesState),
    ("/cucm/cti-route-points", "CTI Route Points", cti_route_points, CtiRoutePointsState),
    ("/cucm/hunt-groups", "Hunt Groups", hunt_groups, HuntGroupsState),
    ("/cucm/route-patterns", "Route Patterns", route_patterns, RoutePatternsState),
    ("/cucm/translation-patterns", "Translation Patterns", translation_patterns, TranslationPatternsState),
    ("/cucm/softkey-templates", "Softkey Templates", softkey_templates, SoftkeyTemplatesState),
    ("/cucm/common-device-configs", "Common Device Configs", common_device_configs, CommonDeviceConfigsState),
    ("/cucm/phone-button-templates", "Phone Button Templates", phone_button_templates, PhoneButtonTemplatesState),
    ("/cucm/mpp-phones", "Physical Phones (MPP)", mpp_phones, MppPhonesState),
]:
    app.add_page(_page, route=_route, title=f"{_title} | {APP_NAME}", on_load=_state.on_page_load)

for _route, _title, _page, _state in [
    ("/cucm/em-bulk-login", "EM Bulk Login", em_bulk_login, EmBulkState),
    ("/cucm/set-user-pin", "Set User PIN", set_user_pin, SetPinState),
]:
    app.add_page(_page, route=_route, title=f"{_title} | {APP_NAME}", on_load=_state.load_connections)

app.add_page(phone_count, route="/cucm/phone-count-by-dp", title=f"Phone Count By DP | {APP_NAME}",
             on_load=PhoneCountState.on_page_load)
