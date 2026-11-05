# CUCM Device Pool Export (Tool 1)

## Context
Build a CUCM tool that finds device pools, lists their phones with owner and line data, and downloads an Excel workbook. The workbook must carry everything a later Webex build tool needs (users, workspaces, calling). Tool 2 (Webex build) is out of scope this round; plan it after seeing a real export. A Hunt Groups worksheet is a later addition, so the workbook builder takes a list of sheets.

## Files
- `webui/uc_automation/backend/cucm_pool_export.py` (new, no Reflex imports): data collection and workbook build.
- `webui/uc_automation/state/cucm_pool_export.py` (new): `PoolExportState(CucmState)`.
- `webui/uc_automation/pages/cucm_pool_export.py` (new): layout via `cucm_page` + `_need_connection`.
- `components/cucm_nav.py`: route `POOL_EXPORT = "/cucm/pool-export"`, entry in **Reports** `GROUPS`, add to `IN_DEVELOPMENT` until verified on a real CUCM.
- `uc_automation.py`: import and `add_page(..., on_load=PoolExportState.load_connections)`.
- `.doc/webui-reflex.md`: document the tool and workbook layout. `BUILD` is bumped only at commit time.

## Reuse
- `cucm_system.list_device_pools`, `PickerMixin` style (`components/webex_picker.py`) and `search_input` for search then multi-select.
- `cucm_axl.sql_rows`, `_call`, `sql_quote`; phone-to-line join pattern from `cucm_devices._line_devices` (`numplan`, `devicenumplanmap`, `routepartition`).
- `cucm_reports.registered_names` (RisPort70, throttled) for registration status.
- `cuc_handlers.build_call_trees` for openpyxl styling and the `_xlsx` backend-var plus `rx.download` pattern in `state/cuc_handlers.py`.
- `DeviceReportState.run_report` for `asyncio.to_thread` + progress polling; `OpLog` closed in `finally`.

## Data collection (backend)
1. Phones in the chosen pools: one SQL on `device` / `devicepool` / `typemodel`, giving device name, MAC, device type (model), protocol, device pool, description.
2. Per phone, `getPhone` with `returnedTags` in a small `ThreadPoolExecutor` (about 4 workers, existing AXL retry): `ownerUserName`, phone template, lines (index, DN, partition, display, line text label, external phone number mask, caller ID display), `busyLampFields`. Lines past the phone's own buttons are KEM/sidecar; flag them from the button template and model. Validate request shapes with zeep `create_message` against `schemas/cucm/<ver>/AXLSoap.xsd` first.
3. Owner resolution, in order, recording which one hit in an **Owner Source** column:
   1. Device Owner User ID (`ownerUserName`).
   2. End user associated devices: build a device -> user map from end users' associated devices (SQL on the enduser/device map table, or `getUser` associatedDevices), used when the device has no owner.
   3. Tertiary: line owner, matching a phone's DN+partition to an end user's primary extension (or the line's associated end users).
   If several users match at one level, take the first and list the rest in a Notes column.
4. End user details for the resolved user: user ID, first name, last name, email (`mailid`).
5. **Type** column: `User` if any user was resolved, otherwise `Workspace`.
6. Registration status via `registered_names` (optional toggle, rate limited).
7. Progress callback to the state; per-device failures go to an Errors sheet, not a failed run.

## Workbook sheets
- **Phones** (consolidated, one row per device, lines included):
  Type (User/Workspace), Device Name, MAC, Device Type, Protocol, Device Pool, Description, Phone Template, Registration Status, User ID, First Name, Last Name, Email, Owner Source, Notes, then repeating line groups `Line N DN`, `Line N Partition`, `Line N Display`, `Line N Label`, `Line N External Mask`, `Line N Caller ID`, for every line index found (columns extend to the highest index in the pool, KEM lines flagged in a `Line N KEM` column or the header).
- **BLFs**: Device Name, BLF Index, Destination, Partition, Label, KEM flag (separate sheet since a KEM can add dozens of rows per phone).
- **Summary** (counts per pool, User vs Workspace, owner source) and **Errors**.
- Reserved for later: **Hunt Groups** (hunt list / line group / pilot membership for these DNs; join pattern in `cucm_hunt.py` lines 79-90).
Stable column names so the Webex tool can read it back with openpyxl.

## UI
Pool search box -> matching pools with checkboxes -> options (registration status) -> Run -> progress text -> preview table of Phones -> Download .xlsx (`cucm-pool-export-<server>-<stamp>.xlsx`, held in `_xlsx`). Title Case labels. Switching connection or org clears results.

## Verification
- `cd webui && .venv/bin/reflex export --frontend-only --no-zip` (compile check).
- Boot with `python3 main.py` (or spare ports), confirm the route returns 200; stop only that PID.
- Run the workbook builder and owner resolution on sample data; open the result with openpyxl to check sheets, headers and User/Workspace logic.
- Build AXL requests with zeep `create_message` against the XSD.
- State plainly that nothing was tested against a real CUCM; SQL column names (end user device map, BLF/KEM storage) are unverified until a first real run.
