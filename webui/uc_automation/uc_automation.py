import reflex as rx

from .backend import applog, uc_bootable, uccx_store
from .config import APP_NAME, PLATFORMS
from .pages.advertised_patterns import advertised_patterns
from .pages.css import css
from .pages.credentials import credentials, webex_callback
from .pages.cuc_handlers import call_map, delete_handlers, list_handlers
from .pages.cuc_home import cuc_home
from .pages.cuc_users import remove_empty, status_check, usage_check
from .pages.cucm_home import cucm_home
from .pages.uccx_home import uccx_home
from .pages.uccx_migrate import migrate as uccx_migrate
from .pages.uccx_script import script_report as uccx_script_report
from .pages import redsky_tools as rs_pages
from .pages.tools_home import tools_home
from .pages.tts import text_to_ulaw
from .pages.bootable import make_bootable
from .pages.regex_tester import regex_tester
from .pages.cube_lgw import lgw_config
from .pages.cucm_home_cluster import home_cluster_locator
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
from .pages.cucm_pool_export import pool_export
from .pages.cucm_reports import device_report
from .pages.cucm_sme_patterns import sme_patterns
from .pages.cucm_cutover import webex_cutover
from .pages.cucm_cleanup import cutover_cleanup
from .state.cucm_pool_export import PoolExportState
from .state.cucm_sme_patterns import SmePatternsState
from .state.cucm_cutover import CutoverState
from .state.cucm_cleanup import CleanupState
from .state.cucm_reports import DeviceReportState
from .pages.tools import em_bulk_login, phone_count, set_user_pin
from .pages.system import codec_lists, device_pools, locations, regions
from .pages.webex_routing import add_numbers, call_forward, call_queues, hunt_groups as webex_hunt_groups, virtual_lines, webex_home
from .pages.webex_dialplan import gateway_dial_plan
from .pages.webex_locations import copy_location, e911, migrate_pstn, schedules
from .pages.webex_reports import locations_report
from .pages.webex_tools import hardware_compatibility
from .pages.webex_naming import naming_check
from .pages.webex_devices import bulk_ata, cucm_gateway, cucm_migrate, device_migrate
from .pages.webex_users import add_workspace, upgrade_license, copy_workspace, create_workspace, delete_users, get_workspace, migrate, reset_pin, voicemail
from .pages.pickup_groups import pickup_groups
from .pages.route_patterns import route_patterns
from .pages.translation_patterns import translation_patterns
from .pages.platform import platform_page
from .pages.settings import settings
from .pages.users import users_page
from .state.advertised_patterns import AdvertisedPatternsState
from .state.css import CssState
from .state.regex_tester import RegexTesterState
from .state.cucm import CucmState
from .state.cuc import CucState
from .state.uccx import UccxState
from .state.uccx_migrate import UccxMigrateState
from .state.uccx_script import UccxScriptState
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
from .state.auth_guard import AuthGuard
from .state.webex_token import TaskRecorder
from .state.logs import LogsState
from .state.settings import SettingsState
from .state.users import UsersState
from .state.webex import WebexState
from .state.webex_devices import BulkAtaState, CucmGatewayState, CucmMigrateState, DeviceMigrateState
from .state.webex_groups import CallQueuesState, HuntGroupsState as WebexHuntGroupsState, VirtualLinesState
from .state.webex_dialplan import GatewayDialPlanState
from .state.webex_locations import CopyLocationState, E911State, MigratePstnState, SchedulesState
from .state.webex_reports import LocationsReportState
from .state.webex_tools import HardwareCompatState
from .state.webex_naming import NamingCheckState
from .state.webex_users import (
    AddWorkspaceState,
    UpgradeLicenseState,
    CopyWorkspaceState,
    CreateWorkspaceState,
    DeleteUsersState,
    GetWorkspaceState,
    MigrateState,
    ResetPinState,
    VoicemailState,
)
from .state.webex_routing import AddNumbersState, CallForwardState, WebexSession
from .state.hunt_groups import HuntGroupsState
from .state.partitions import PartitionsState
from .state.cucm_home import HomeClusterState
from .state.tools import EmBulkState, PhoneCountState, SetPinState
from .state.system import CodecListsState, DevicePoolsState, LocationsState, RegionsState
from .state.pickup_groups import PickupGroupsState
from .state.route_patterns import RoutePatternsState
from .state.translation_patterns import TranslationPatternsState

applog.prune_if_due()  # apply the log retention settings at startup
uc_bootable.clean_leftovers()  # temp ISO folders from an earlier crashed run
uccx_store.clean_leftovers()  # zip export folders from an earlier crashed run
uccx_store.prune()  # the stored UCCX download, once it is older than a week

app = rx.App(
    head_components=[rx.el.link(rel="icon", href="/slab42.jpg")],
    api_transformer=[uc_bootable.download_app(), uccx_store.download_app()],  # one-time download routes (Make ISO Bootable, UCCX zip export)
)

app.add_middleware(AuthGuard())  # drops every event from a browser that is not signed in
app.add_middleware(TaskRecorder())  # remembers the Webex task event so a 403 can offer a rerun

app.add_page(home, route="/", title=APP_NAME)
app.add_page(users_page, route="/users", title=f"Users | {APP_NAME}", on_load=UsersState.on_page_load)
for _p in PLATFORMS:
    if _p.slug in ("cucm", "cuc", "uccx", "cube", "webex", "redsky", "tools"):
        continue
    app.add_page(platform_page(_p), route=f"/{_p.slug}", title=f"{_p.label} | {APP_NAME}")
app.add_page(tools_home, route="/tools", title=f"Tools | {APP_NAME}")
app.add_page(make_bootable, route="/tools/make-bootable", title=f"Make ISO Bootable | {APP_NAME}")
app.add_page(text_to_ulaw, route="/tools/text-to-ulaw", title=f"Text To U-Law Audio | {APP_NAME}")
app.add_page(regex_tester, route="/tools/regex-tester", title=f"Regex Tester | {APP_NAME}",
             on_load=RegexTesterState.on_page_load)
app.add_page(cube_home, route="/cube", title=f"CUBE | {APP_NAME}")
app.add_page(mem_status, route="/cube/mem-status", title=f"CUBE Mem Status | {APP_NAME}",
             on_load=MemStatusState.load_page)
app.add_page(config_compare, route="/cube/config-compare", title=f"CUBE Config Compare | {APP_NAME}",
             on_load=ConfigCompareState.load_page)
app.add_page(lgw_config, route="/cube/lgw-config", title=f"CUBE Webex LGW Config | {APP_NAME}")
app.add_page(webex_home, route="/webex", title=f"Webex | {APP_NAME}", on_load=WebexSession.on_page_load)
app.add_page(add_numbers, route="/webex/add-numbers", title=f"Add Numbers | {APP_NAME}",
             on_load=AddNumbersState.load_page)
app.add_page(call_forward, route="/webex/call-forward", title=f"Call Forward | {APP_NAME}",
             on_load=CallForwardState.on_page_load)
for _route, _title, _page, _state in [
    ("/webex/call-queues", "Call Queues", call_queues, CallQueuesState),
    ("/webex/hunt-groups", "Webex Hunt Groups", webex_hunt_groups, WebexHuntGroupsState),
    ("/webex/virtual-lines", "Virtual Lines", virtual_lines, VirtualLinesState),
    ("/webex/gateway-dial-plan", "Gateway Dial Plan", gateway_dial_plan, GatewayDialPlanState),
    ("/webex/migrate", "Migrate", migrate, MigrateState),
    ("/webex/schedules", "Schedules", schedules, SchedulesState),
    ("/webex/e911", "E911", e911, E911State),
    ("/webex/copy-location", "Copy Location", copy_location, CopyLocationState),
    ("/webex/migrate-pstn", "Migrate PSTN", migrate_pstn, MigratePstnState),
    ("/webex/hardware-compatibility", "Check Hardware Compatibility", hardware_compatibility, HardwareCompatState),
    ("/webex/naming-check", "Naming Check", naming_check, NamingCheckState),
    ("/webex/locations-report", "Locations Report", locations_report, LocationsReportState),
]:
    app.add_page(_page, route=_route, title=f"{_title} | {APP_NAME}", on_load=_state.load_page)
for _route, _title, _page, _state in [
    ("/webex/delete-users", "Delete Users", delete_users, DeleteUsersState),
    ("/webex/reset-pin", "Reset PIN", reset_pin, ResetPinState),
    ("/webex/create-workspace", "Add Workspace", create_workspace, CreateWorkspaceState),
    ("/webex/copy-workspace", "Copy Workspace", copy_workspace, CopyWorkspaceState),
    ("/webex/get-workspace", "Get Workspace", get_workspace, GetWorkspaceState),
    ("/webex/upgrade-license", "Upgrade Calling License", upgrade_license, UpgradeLicenseState),
    ("/webex/add-workspace", "Add Device", add_workspace, AddWorkspaceState),
    ("/webex/bulk-ata", "Bulk ATA/VG", bulk_ata, BulkAtaState),
    ("/webex/webex-phone-migrate", "Webex-Webex Phone Migrate", device_migrate, DeviceMigrateState),
    ("/webex/cucm-phone-migrate", "CUCM-Webex Phone Migrate", cucm_migrate, CucmMigrateState),
    ("/webex/cucm-gateway-migrate", "CUCM-Webex Analog Gateway Migrate", cucm_gateway, CucmGatewayState),
    ("/webex/voicemail", "Voicemail", voicemail, VoicemailState),
]:
    app.add_page(_page, route=_route, title=f"{_title} | {APP_NAME}",
                 on_load=_state.load_page if _state in (AddWorkspaceState, BulkAtaState, DeviceMigrateState, CucmMigrateState, CucmGatewayState, CopyWorkspaceState, CreateWorkspaceState, UpgradeLicenseState, GetWorkspaceState, VoicemailState) else _state.on_page_load)
app.add_page(logs, route="/logs", title=f"Logs | {APP_NAME}", on_load=LogsState.on_page_load)
app.add_page(settings, route="/settings", title=f"Settings | {APP_NAME}", on_load=SettingsState.on_page_load)

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
app.add_page(uccx_home, route="/uccx", title=f"UCCX | {APP_NAME}", on_load=UccxState.load_connections)
app.add_page(uccx_migrate, route="/uccx/migrate", title=f"UCCX Migrate | {APP_NAME}",
             on_load=[UccxState.load_connections, UccxMigrateState.load_page])
app.add_page(uccx_script_report, route="/uccx/script-report", title=f"UCCX Script Report | {APP_NAME}",
             on_load=[UccxState.load_connections, UccxScriptState.load_page])
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
    ("/redsky/primary-location", "Check Primary Location Exists", rs_pages.primary_location),
    ("/redsky/alerts-check", "Check All Buildings", rs_pages.alerts_check),
    ("/redsky/import-precheck", "Import Precheck", rs_pages.import_precheck),
    ("/redsky/duplicate-buildings", "Find Duplicate Buildings", rs_pages.duplicate_buildings),
    ("/redsky/duplicates-remediate", "Remediate Duplicate Buildings", rs_pages.duplicates_remediate),
    ("/redsky/no-locations", "Find Buildings Without Locations", rs_pages.no_locations),
    ("/redsky/no-tracking", "Find Locations Without Device Tracking", rs_pages.no_tracking),
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
    on_load=[CucmState.load_connections, CucState.load_connections, UccxState.load_connections,
             RedskyState.load_connections,
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

app.add_page(sme_patterns, route="/cucm/sme-adv-route-patterns", title=f"SME Adv & Route Patterns | {APP_NAME}",
             on_load=SmePatternsState.load_connections)
app.add_page(webex_cutover, route="/cucm/webex-cutover", title=f"Webex Cutover | {APP_NAME}",
             on_load=CutoverState.load_connections)
app.add_page(cutover_cleanup, route="/cucm/cutover-cleanup", title=f"Cutover Cleanup | {APP_NAME}",
             on_load=CleanupState.load_connections)
app.add_page(home_cluster_locator, route="/cucm/home-cluster-locator", title=f"Home Cluster Locator | {APP_NAME}",
             on_load=HomeClusterState.load_connections)
app.add_page(device_report, route="/cucm/device-report", title=f"Device Report | {APP_NAME}",
             on_load=DeviceReportState.load_connections)
app.add_page(pool_export, route="/cucm/device-export-webex", title=f"Device Export for Webex | {APP_NAME}",
             on_load=PoolExportState.load_connections)
app.add_page(phone_count, route="/cucm/phone-count-by-dp", title=f"Phone Count By DP | {APP_NAME}",
             on_load=PhoneCountState.on_page_load)
