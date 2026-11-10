# Reflex web UI (`webui/`)

The only front end of this repo (the old CLI scripts and the `gui/` wrapper were removed; see git history). Each feature is
Python backend code (AXL, REST or SSH calls) plus a Reflex page. Build number: `BUILD` in
`webui/uc_automation/config.py`.

Run: `python3 main.py` from the repo root (creates `webui/.venv` on first run), or `cd webui && .venv/bin/reflex run` (UI on :3000, backend on :8000, localhost only).
Setup: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
Compile check: `.venv/bin/reflex export --frontend-only --no-zip` (fails on any bad page).

## Layers

Every feature has the same three layers. Keep them separate.

| Layer | Folder | Job |
|---|---|---|
| Backend | `uc_automation/backend/` | Plain Python. AXL calls, credential storage. No Reflex imports. |
| State | `uc_automation/state/` | Reflex state classes: what the page knows and does. Calls the backend in a thread. |
| Page | `uc_automation/pages/`, `components/` | Layout only. Reads state vars, binds buttons to state handlers. |

```
backend/cucm_axl.py          shared plumbing only: AxlError, schema/version, cached zeep client, `_call`, `list_paged`, `sql_rows`. Every AXL call goes through `_Service`: network/5xx problems become `AxlError`, reads (get/list/SQL) retry twice on a reset connection or HTTP 502/503/504, writes never retry
backend/cucm_routing.py      advertised patterns, partitions, calling search spaces, call pickup groups, route patterns, translation patterns
backend/cucm_hunt.py         hunt pilots, plus hunt list / line group cleanup and the line group dependency check
backend/cucm_system.py       System: audio codec preference lists, regions, locations, device pools (+ SQL dependency checks)
backend/cucm_dn.py           directory numbers: move partition, alternate numbers, orphans (SQL)
backend/uc_bootable.py       Make ISO Bootable: pycdlib El Torito boot record, temp job folder, one-time download route
backend/tts_ulaw.py          Text To U-Law Audio: gTTS speech, PyAV decode/resample/u-law WAV (all in memory), prompt CSV parsing
backend/cucm_home.py         Home Cluster Locator: UDS clusterUser lookup per cluster
backend/cucm_tools.py        tools: EM bulk login/logout/check, phone count by device pool, set user PIN
backend/cucm_reports.py      Reports: Device Report (AXL phones and pools, RisPort70 registration, SQL gateway count per device pool)
state/cucm_reports.py        DeviceReportState; page in pages/cucm_reports.py
backend/cucm_pool_export.py  Device Export for Webex: SQL device list, AXL getPhone per phone, SQL end users, xlsx workbook
state/cucm_pool_export.py    PoolExportState; page in pages/cucm_pool_export.py
backend/cucm_sme_patterns.py SME Adv & Route Patterns: settings defaults and checks, description templates, number formatting, CSV parsing, add pair
state/cucm_sme_patterns.py   SmePatternsState; page in pages/cucm_sme_patterns.py
backend/cucm_cutover.py      Webex Cutover: DN list parsing, wrappers over cucm_dn and cucm_sme_patterns
state/cucm_cutover.py        CutoverState; page in pages/cucm_cutover.py
backend/cucm_cleanup.py      Cutover Cleanup: delete devices and orphan DNs, line groups with DNs, unused object scans
state/cucm_cleanup.py        CleanupState; page in pages/cucm_cleanup.py
state/sme_settings.py        SmeSettingsMixin: the SME pattern settings, variables and variable regexes (shared by SME Adv & Route Patterns and Webex Cutover); sections in components/sme_settings.py
backend/keys.py              composite row keys (pattern + partition) shared by backend and state
backend/cucm_devices.py      phones, CTI route points (delete cleans up orphaned DNs), softkey templates, common device configs, button templates, MPP workflows
backend/organizations.py     customer organizations ([ORG:<name>]), per-organization filtering and grouping helpers
backend/cucm_connections.py  saved CUCM connections ([CUCM:<name>] in .env/credentials.env)
backend/cuc_connections.py   saved CUC connections ([CUC:<name>]), same shape as CUCM
backend/cuc_api.py           CUC REST plumbing: CucError, schema pick, `detect_version` (GET /vmrest/version), CucClient (paged GET, DELETE, users/mailboxes, call handlers, menu entries)
backend/uccx_connections.py  saved UCCX connections ([UCCX:<name>]: server, username, password, org)
backend/uccx_api.py          UccxError, UccxClient (admin API /adminapi and Finesse :8445, one login; reads retry, writes never), `self_href`, `local_name`
backend/uccx_store.py        the one stored download (`webui/uccx_download/`, git-ignored): start/finish/current/delete/prune, zip export, one-time `/uccx-export/<token>` route
backend/uccx_backup.py       Migrate download: `AREAS` (admin settings, application/CCG/team details, prompt and script files, Finesse settings, phone books, teams)
backend/uccx_restore.py      Migrate upload: `STEPS` (18 functions, port of the numbered upload scripts) with `Ctx`, `Options` and `Tally`
backend/uccx_aef.py          UCCX script (.aef) reader (Java serialization, no Cisco classes) and HTML report
backend/cube_ssh.py          CubeError, Router, parse_routers (router_ip,hostname CSV), run_command (netmiko, cisco_ios, port 22)
backend/cube_mem.py          Mem Status parsing (free % of RP0/RP1, memory section), CSV export
backend/cube_config.py       Config Compare: voice section parser, comparator, HTML report
backend/cube_lgw.py          Webex LGW Config Generator: validation and config text (port of the Flask LGW tool)
backend/cube_credentials.py  named router credential sets ([CUBE:<name>]: username, password)
backend/redsky_connections.py  saved RedSky connections ([REDSKY:<name>]: username, password, org_id)
backend/redsky_api.py        RedskyError, RedskyClient (login, 15 min token renewal, geography/networking/alert calls; raises RedskyError), `check_login`
backend/redsky_common.py     Field / AddSpec / CheckSpec (one spec drives form, CSV template, parser and run loop), CSV rows, location lookup
backend/redsky_geography.py  Add Buildings, Add Locations specs
backend/redsky_precheck.py   Import Precheck: parse pasted/CSV names or IP ranges, check Buildings, Locations or Private IP ranges against RedSky
backend/redsky_alerts.py     Add-Edit Alerts, Check Buildings specs
backend/redsky_networking.py BSSID, LLDP, Private IP, Public IP specs
backend/cuc_users.py         CUC users: extension list parsing, status/usage rows and CSV
backend/cuc_handlers.py      CUC call handlers: classify, menu entries, CSV in/out, call tree workbook (openpyxl)
backend/errors.py            UserError: base of AxlError, WebexError, WebexAuthError (run loops catch it)
backend/webex_api.py         WebexClient: one per operation, token checked once, `orgId` added to every call, one pooled `requests.Session` (keep-alive), 429 retry
backend/paste.py              PastedFile: pasted text as a stand-in for an uploaded CSV (delimiter detection, optional header)
backend/webex_dialplan.py    Gateway dial plans: create, add dial patterns
backend/webex_routing.py     Add Numbers and Call Forward All (set/remove) calls and CSV parsers
backend/webex_groups.py      Call queues and hunt groups: lists, create from CSV, replace agents, migrate hunt group to queue
backend/webex_virtual_lines.py  Virtual line busy/unanswered voicemail greeting upload
backend/webex_users.py       Delete users, reset voicemail PIN
backend/webex_voicemail.py   Voicemail report: internal vs external mailbox per user (single user or a location)
backend/webex_reports.py     Locations Report: Calling users and Calling workspaces per location (state/webex_reports.py, pages/webex_reports.py)
backend/webex_devices.py     Webex-Webex Phone Migrate (move a phone between Webex orgs)
backend/webex_cucm_migrate.py CUCM-Webex Phone Migrate (either direction)
backend/webex_cucm_gateway.py CUCM-Webex Analog Gateway Migrate (read ports from CUCM, workspaces and device in Webex)
backend/webex_workspaces.py  Create workspaces, add devices to workspaces, move users to another location (Move Users job)
backend/webex_locations.py   Location schedules (export/update/copy/remove past), RedSky E911 status/opt-out and PSTN connection migration
backend/webex_tools.py       Hardware compatibility check (supported models + validateMacs)
backend/webex_naming.py      Naming Check: list locations, queues, hunt groups, auto attendants, workspaces, virtual lines; regex check; rename
backend/webex_auth.py        Webex OAuth login, token storage/refresh ([WEBEX:default]); `ensure_token()` for API code
backend/webex_personal.py    personal Webex token per app user (`.env/webex_personal.json`, git-ignored): save, status (missing, stale after 6 h, expired, ok)
backend/applog.py            operation logs: OpLog writer, pruning (`prune_logs`), plus list/read/export helpers for the Logs page
backend/app_settings.py      `webui/app_settings.json` (git-ignored): log retention days and max size, defaults 90 days / 2048 MB
backend/ini_store.py         comment-preserving credentials.env editor
backend/users.py             app users (`webui/users.json`, git-ignored): scrypt password hashes, in-memory sign-in sessions, per-user route lists, `can_open`
state/auth.py                AuthState (root): session token (browser LocalStorage `auth_token`), sign in, first-run Admin setup, sign out, change own password
state/auth_guard.py          AuthGuard middleware: drops every event from a browser that is not signed in (and from a page the user may not open)
state/users.py               UsersState (Admin only): users, access tree, password reset; builds the permission catalog from `state/search.INDEX`
pages/users.py               Users page (`/users`)
components/login.py          sign-in / first-run setup screens, account menu (top bar), change password dialog, Webex Token dialog, 403 offer dialog
state/webex_token.py         WebexTokenState (Webex Token window, switch to personal token, rerun) and TaskRecorder middleware
components/access.py         `show_if`, `show_if_any`, `allowed`, `platform_visible`: hide menu items, cards and tiles the user may not open
state/logs.py                LogsState: Logs page (search, read, export; no delete or import)
state/favorites.py           FavoritesState: favorite and recent function routes (browser LocalStorage `favorite_routes`, `recent_routes`)
state/search.py              SearchState: home page search over the GROUPS of the CUCM, CUC and Webex menus (platform, section, link)
state/run_mixin.py           RunMixin: busy/progress/per-row results and the background run (`_start_run`, `run_job`, `cancel_run`); CrudMixin inherits it
state/webex_tools.py         Check Hardware Compatibility state
state/webex_naming.py        Naming Check state
state/webex_devices.py       Bulk ATA/VG, Webex-Webex Phone Migrate, CUCM-Webex Phone Migrate and CUCM-Webex Analog Gateway Migrate states
state/webex_users.py         Delete Users, Reset PIN, Voicemail, Add Workspace, Add Device, Migrate states
state/webex_locations.py     Schedules, E911 and Migrate PSTN states
state/webex_groups.py        PickerMixin (searchable list + selection) and the Call Queues / Hunt Groups / Virtual Lines states
state/webex_routing.py       WebexSession (login status in the menu bar, checked on page load) + Add Numbers / Call Forward states
state/webex.py               WebexState: Webex tab on the credentials page and the /webex/callback page
state/org.py                 OrgState: parent of every platform state (organization list, active organization, organization window)
state/bootable.py            BootableState: streamed ISO upload, make bootable, download, delete
pages/bootable.py            Make ISO Bootable page (Tools platform)
state/tts.py                 TtsState: Text To U-Law Audio
pages/tts.py                 Text To U-Law Audio page (Tools platform)
pages/regex_tester.py        Regex Tester page (Tools platform)
state/regex_tester.py        RegexTesterState
backend/regex_tester.py      Regex run in a child interpreter with a timeout
components/regex_ref.py      Regex quick reference (click a token to add it)
state/cucm_home.py           HomeClusterState: user lookup across the organization's CUCM connections
pages/cucm_home_cluster.py   Home Cluster Locator page
state/cucm.py                CucmState: connection list, active connection, credentials form, Test button
state/cube_tools.py          CubeRun mixin (router list, credential set picker) + MemStatusState, ConfigCompareState
components/cube_nav.py       CUBE top menu bar (GROUPS), cred_picker, cube_page()
pages/cube_tools.py          CUBE home cards, Mem Status and Config Compare pages
state/cube_lgw.py            LgwState: LGW form, generate, TXT export
pages/cube_lgw.py            Webex Local Gateway Config Generator page
state/cube.py                CubeState: credential set list and form (Credentials > CUBE)
state/redsky.py              RedskyState: connection list, active connection, credentials form, Test button
state/redsky_tools.py        RedskyBulk / RedskyCheck mixins (all handlers) + one tiny state per tool
components/redsky_nav.py     RedSky top menu bar (GROUPS), connection picker, redsky_page(), need_connection()
pages/redsky_tools.py        home cards, generic add_page(S, spec) and check_page(S, spec)
state/uccx.py                UccxState: connection list, active connection, credentials form, Test button
state/uccx_migrate.py        UccxMigrateState: stored download prompt, download, upload steps and options
state/uccx_script.py         UccxScriptState: Script Report (stored scripts or uploads, preview, download)
components/uccx_nav.py       UCCX top menu bar (GROUPS: Migration, Scripts), uccx_page(title, ..., show_instance)
pages/uccx_home.py, pages/uccx_migrate.py, pages/uccx_script.py   UCCX home cards, Migrate and Script Report pages
state/cuc.py                 CucState: same for CUC; plus CucRun (RunMixin + failed_results)
state/cuc_users.py           Status Check, Usage Check, Remove Empty states
state/cuc_handlers.py        List, Map, Delete states
components/cuc_nav.py        CUC top menu bar (GROUPS: Users, Call Handlers), connection picker, cuc_page(), need_connection()
components/cuc_widgets.py    failures table (only failed rows), data_table, list_input (paste | CSV), all_rows_view (searchable checkbox list)
state/crud.py                CrudMixin + ResourceSpec: the shared list/search/select/add/import/export/delete logic
state/<resource>.py          one tiny class per resource: `class XState(CucmState, CrudMixin)` + a spec
components/crud_page.py      build_crud_page(): the shared page (toolbar, table, all dialogs)
components/webex_picker.py   picker(): search + click-to-select table for a PickerMixin state
components/webex_nav.py      Webex top menu bar (GROUPS) and webex_page(); shows org and login status
components/search_input.py   search_input(value, on_change, placeholder): every search box uses it (clear button once there is text)
components/org_picker.py     org_select(): the organization dropdown beside each platform's connection dropdown
pages/organizations.py       Credentials > Organizations tab and organization window
components/cucm_nav.py       CUCM top menu bar. GROUPS drives the menu and the CUCM home cards
components/layout.py         sidebar, top bar, page() wrapper (sidebar collapses to icons via the toggle by the build number, flag in state/sidebar.py, kept in browser LocalStorage)
pages/<resource>.py          one config per resource (columns, add form)
uc_automation.py             app + every add_page()
```

## Logging

- Every operation writes its own text file to `webui/logs/` (git-ignored): `<YYYY-MM-DD_HH-MM-SS>-<slug>.log`,
  first line `<Title> - Started`, last line `<Title> - Completed`.
- Every log line carries the signed-in user's name (`%(user)s`, after the level). `AuthGuard` calls `applog.set_user` for each event and `OpLog` reads it (`system` when none); sign-in events pass `user=` to `log_event`.
- Use `OpLog(title, slug)` from `backend/applog.py` and close it in `try/finally`. On CRUD pages call
  `self._open_log("Action")` (builds title and slug from the spec). Pass the log into `_start_each(..., log)`;
  the run owns it from there (`OpLog.hold`/`release`). The reload after a run is the `fetch` event, with its own "List" log.
- Covered: list/reload, add, import add/modify, delete selected, bulk delete, export, dependency check, MPP
  migrate/prep, and save/test/delete connection. New features must log too. Never log passwords.
- Logs page (`/logs`, sidebar above Credentials): newest first, search matches file names and contents,
  click a row to read it, select one or more and Export (one `.log`, or a `.zip` for several). It has no delete
  or import on purpose. The viewer and the content search read only the last 1000 lines of each log (`applog.LINE_LIMIT`); Export gives the whole file.
  Old logs are pruned by `applog.prune_logs`: older than `log_retention_days` (default 90), then oldest first while the total is over `log_max_mb` (default 2048); 0 turns a limit off. It runs at app start, before a log opens (at most every 10 minutes) and when Settings > Log Retention is saved. The Log Retention card is only shown to the Admin account (`rx.cond(AuthState.is_admin, ...)`), and `SettingsState` (an `AuthState` subclass) re-checks the Admin role in the save and reset handlers. Logs being written are never pruned.
  The Parser mode switch replaces the file list with the last 200 log lines (newest first)
  across all logs, filtered by the search text when there is one (`applog.parse_logs`). File names from the browser are validated against a strict pattern before any read.
- Not logged: template downloads, selection/search clicks, dialog open/close, and CSV rejections on the MPP page.

## Credentials

### Organizations

- The tool is multi customer. An organization is a `[ORG:<name>]` section; every saved platform entry (`[CUCM:x]`, `[CUC:x]`,
  `[CUBE:x]`, `[WEBEXORG:x]`, `[REDSKY:x]`) carries an `org = <name>` key. Entries without one show as **Unassigned** until
  edited. An organization with entries cannot be deleted. "Unassigned" is a reserved name.
- Credentials > **Organizations** (first tab): the list, Add Organization, and an organization window (click a row) with an
  Add button per platform and the entries it holds (several of each allowed). Add/Edit opens that platform's own form in a
  dialog on top of the window; saving closes it and the window behind shows the change. The forms are the ones the platform tabs use.
- Every platform form starts with an **Organization** line (required). The saved lists on the platform tabs are grouped by organization.
  The Webex tab's own list of orgs is now titled Webex Organizations (a Webex org belongs to a customer organization). Webex logins are
  not tied to an organization.
- Every platform state subclasses `OrgState` (`state/org.py`), so `active_org` (browser LocalStorage) is shared. Function pages show an
  organization dropdown (`components/org_picker.py`) before the connection dropdown; the connection list is filtered to that organization
  (`org_connections`, `webex_org_names`, `CubeRun._filter_creds`). Changing it re-picks the active connection (`_reconcile`); CRUD pages and
  Phone Count By DP also reload (`switch_org`), Webex reloads the page. Platform states load organizations through `_load_orgs()`.
- **Output is cleared on a change.** A state lists the vars that hold its results, reports, plans or lookups in
  `output_fields: ClassVar[tuple[str, ...]]` (`RunMixin`, `CrudMixin`, `DepCheckMixin` and the other mixins list theirs; the MRO is
  merged). Every organization or instance handler (`select_org`, `select_active`, `select_webex_org`, `set_cred_name`, the
  `switch_org` and `switch_connection` handlers) awaits `OrgState._clear_outputs(whole_org)`, which resets those vars on every page
  state: all platforms for an organization change (they share `active_org`), the platform's own pages for an instance change. A page
  that is running (`busy`) is left alone. Inputs (pasted text, forms) are kept. Add new output vars to `output_fields`.

### Connections

- Stored in `.env/credentials.env` as `[CUCM:<name>]` with `server`, `username`, `password`,
  `version` (detected CUCM release) and `schema_version` (AXL schema folder used), plus an optional `subscribers` line
  (comma separated `host` or `host|em`; `|em` = the subscriber runs Extension Mobility). The form lists subscribers
  with an EM checkbox each (`form_subs`, `add_subscriber`, `toggle_sub_em`, `remove_subscriber` in `state/cucm.py`);
  nothing uses them for calls yet. Not tested against a real CUCM.
- The form has an **SME cluster** checkbox (`form_sme`, `set_sme`), saved as `sme = yes|no`; SME Adv & Route Patterns only runs on a connection with it ticked.
- Passwords never reach the browser. The password input is uncontrolled and feeds a **backend var**
  (`_password`, underscore prefix = not sent to the client). Saved passwords show only as "Stored".
- The Test button calls `getCCMVersion`, derives the major release (for example 14.0), picks the
  closest installed schema (`webui/uc_automation/schemas/cucm/<version>/`, exact match else nearest older), and saves both.
- Schemas are tracked in git under `webui/uc_automation/schemas/<platform>/<version>/` (`cucm`, `cuc`); a new platform gets its own folder and a constant in `backend/paths.py`.
- The webui keeps its own copy of the schemas.

### CUC credentials

- Credentials > CUC works like CUCM: `[CUC:<name>]` with `server`, `username`, `password`, `version`, `schema_version` and an optional
  `subscriber` (at most one host, a plain input with no Add button, saved with the cluster when filled in; nothing uses it for calls yet).
  The page builders in `pages/credentials.py` (`_conn_tab`) are shared and take the state class.
- Test calls `GET https://<server>/vmrest/version`, takes the major release, picks the closest schema folder under
  `schemas/cuc/<version>/` (only 15.0 today) and saves both. Port 443, basic auth, TLS not verified.
- Not tested against a real CUC (the version call was checked against a local fake server only).

### UCCX credentials

- Credentials > UCCX works like CUC: `[UCCX:<name>]` with `server`, `username`, `password`, `org`. The same login is used for the admin API
  (`https://<server>/adminapi`) and Finesse (`https://<server>:8445/finesse/api`). Test lists the skills (proves the login) and saves. No version is detected.

### CUBE credentials

- Credentials > CUBE stores named sets: `[CUBE:<name>]` with `username` and `password`. A set is not tied to a router, so
  several routers can share one. A set named `default` is preselected on the CUBE pages.
- No Test button yet (a set has no router to test against). Saves and deletes are logged without the password.

### CUBE features

- **Webex Local Gateway Config Generator** (`/cube/lgw-config`): form for the Webex trunk (tenant ID, OTG/DTG, proxy, registrar, line/port,
  credentials, interfaces, public gateway) and up to 6 CUCM nodes; Generate shows the CUBE config on screen, Export TXT downloads it.
  No router access. Deliberate exception to the passwords rule: the generated config shows the trunk and STUN passwords on screen and in the TXT (the inputs are not saved or logged).
  Port of the Flask LGW tool; the template lives in `backend/cube_lgw.py`. Untested on a real CUBE.

- Menu (`components/cube_nav.GROUPS`, also the `/cube` home cards): **Health** = Mem Status; **Configuration** = Config Compare, Webex Local Gateway Config Generator.
  Port of `cube/check_router_mem_status.py` and `cube/compare_router_config.py` (reference only).
- No router list is stored. Each run takes routers from Paste Text (first) or CSV (`router_ip,hostname`, header optional, same layout
  as the old `routers.csv`) and one saved credential set picked in a dropdown (`default` preselected), or **Enter Manually** (username and password fields, held in
  backend vars for the session, never written to `credentials.env`, never logged). Routers run one by one over SSH.
- **Mem Status** runs `show platform software status control-processor br`, reads the free % and flags routers below the threshold
  (field on the page, default 33). Export CSV is a browser download. There is no summary email.
- **Config Compare** takes the template as pasted text or a loaded file (the file fills the text box), runs `show running-config`,
  compares the voice sections and builds one HTML report per router. Download Reports gives one `.html`, or a `.zip` for several,
  as browser downloads. Export CSV gives the results table.
- Needs `netmiko` (in `requirements.txt`). Not tested against a real router: the parsers and report were run on sample text, and the app compiles.

### RedSky credentials

- Credentials > RedSky works like CUCM: `[REDSKY:<name>]` with `username`, `password`, `org_id`.
- Test logs in (`POST /auth-service/login`), then lists the organization's buildings to prove the org ID, and saves on success.
- Not tested against a real RedSky tenant. Only the page compile was checked.

### RedSky features

- Menu (`components/redsky_nav.GROUPS`, also the `/redsky` home cards): **Buildings And Locations** = Add Buildings, Add Locations; **Tools** = Import Precheck, Remediate Duplicate Buildings (in development, `redsky_nav.IN_DEVELOPMENT`: hidden unless the Experimental setting is on); **Alerts** = Add-Edit Alerts, Check Buildings; **Tracking** = BSSID, LLDP, Private IP, Public IP; **Reports** (last) = Check Primary Location Exists, Find Duplicate Buildings, Find Buildings Without Locations, Find Locations Without Device Tracking.
  One active connection (picker in the menu bar, shared with the Credentials tab). Port of `redsky/*.py` (reference only).
- **Add tools** share one page (`add_page`) built from an `AddSpec`: a single entry form (one field per CSV column, suggestions
  for buildings, locations, alert types and templates), then Paste Text (first) and CSV tabs that go through the same handler,
  a Download Template button and a per-row result table. Column order is the Download Template order (header row skipped).
  Pasted text may be tab, pipe or comma separated (not semicolon: it separates items inside a cell); quote addresses with commas.
- **Check tools** (`check_page`, `CheckSpec`) run on demand, list the problems and Export CSV (browser download).
- **Import Precheck** (`/redsky/import-precheck`, `PrecheckState`, `page import_precheck`, menu **Tools**) is its own page: a
  Buildings | Locations | Private IPs radio at the top of the input card, above Paste Text (first) and CSV (one radio for both).
  Buildings: name in the first column, optional full address in the second (tab or `|`); columns Input Building, Input Address (as entered), Status, Conflict Building, Conflict Address (the conflicting Buildings looked up in RedSky: the same-name Building when its address differs, plus any other Building on the input address; several are joined with `; `). The name is
  checked first, then the address against every other Building (`same_address`: punctuation and street words normalized, RedSky's
  trailing city/state/zip allowed). Status: Exists (name found, address matches or not given), Exists - Address Differs, Exists - Address
  Conflict, Address Conflict (new name, address already used; the Conflict columns name the Building), Not Found, Duplicate In List. The
  Building address field name in RedSky's list response is unverified (`building_address` tries several); with none found the run
  stops and lists the fields so it can be fixed. Locations: Location first, Building second (tab or `|` when pasted, so names may hold commas)
  or `Building / Location`; a Location without a Building matches in any Building. Private IPs: low and high address (tab, `|`, comma,
  space or `-`), a single address, or a CIDR block. Status per row: Exists, Not Found, Duplicate In List, Building Not Found
  (Locations), Overlaps and Invalid (Private IPs: Overlaps = shares addresses with a different existing range). Export CSV is a
  browser download. Private IPs results have their own columns: Name, Status, Building and Address (of the Location the existing range is tied to), Location, Range (the existing range it matches or overlaps). Logged as one operation. The Private IP list call (`RedskyClient.list_ip_ranges`, `GET
  /networking-service/ipRange/company/{org}`) is a guess by analogy with the switch list: the reference JSON has no networking
  endpoints, so verify the path and the location field on a real tenant.
- **Audit** (`backend/redsky_audit.py`, menus **Reports** and **Tools**). Device tracking = static MACs, LLDP (switches and ports), BSSIDs and
  Private IP ranges, each tied to a Location; a Building's tracking is that of its Locations (`collect_tracking`).
  - **Find Duplicate Buildings** (`/redsky/duplicate-buildings`, `DuplicatesState`): Buildings grouped by address (`same_address`),
    one row per Building on screen. The export is an Excel file
    (`duplicate_workbook`, openpyxl): Group, Building, Correct Building Name (TRUE/FALSE dropdown, FALSE by default, red when a group
    has more than one TRUE: a list dropdown cannot also enforce that), Address, Locations (count), then one `Location N` column per Location name. A Building name is yellow (also on screen) when a
    Location name from its group, at least 3 characters and not equal to the Building name, is contained in it
    (`suspect_building_name`): a Building name with a Location glued on.
  - **Remediate Duplicate Buildings** (`/redsky/duplicates-remediate`, `RemediateState`): Find Duplicates, pick the Building to keep per
    address (default: most Locations), Preview (counts only, nothing changed), then Remediate behind a confirm dialog. Per Location of
    a duplicate: find the same-name Location in the kept Building (`<dup> - Entire Site` maps to `<kept> - Entire Site`) or create it,
    PUT each tracking record onto it, delete the old Location; then delete the duplicate Building, only if every step before it worked.
    Each step is a row of the run result table. The plan is read from RedSky again when Remediate starts.
  - **Check Primary Location Exists** (`/redsky/primary-location`, `PrimaryLocationState`): a `CheckSpec` with an input (`input_label`; the page asks
    for a value passed to `run`). The user types the primary Location name, `{building}` standing for the Building's name; Buildings with no
    Location of that name (case-insensitive) are listed with their address and the name expected. Nothing is hard-coded to "Entire Site".
  - **Find Buildings Without Locations** (`/redsky/no-locations`) and **Find Locations Without Device Tracking** (`/redsky/no-tracking`)
    are `CheckSpec` pages. The tracking check stops with an error if any of the four lists cannot be read, so a Location is never
    reported untracked because a list was missing.
  - In **Check Buildings** (`/redsky/alerts-check`) the Building name is a link: `AlertsCheckState.open_in_add_alerts` fills the
    Add-Edit Alerts form (name and scope = the Building) and redirects to `/redsky/alerts-add` (`check_page(..., link_handler)`).
  - **Add-Edit Alerts** (`/redsky/alerts-add`) has an **Edit** tab after the Add tabs. It loads nothing until the user searches (alert name
    contains text, empty lists all); clicking an alert loads it (`alerts.load_alert`) into `AddAlertsState.edit_row`; Save PUTs the subscription
    and replaces its scope only if it changed (`alerts.save_alert`). User and Informacast recipients and scope entries the form cannot
    show are kept unchanged. Uses `/admin-service/alertSubscription` PUT, GET by id and DELETE on `/{id}/filters`. The tracking check has an optional "Location Name Contains" input (`CheckSpec.input_optional`):
    when filled, only Locations whose name contains the text (case-insensitive) are checked and reported, and the total counts only those.
  - Unverified against a real tenant: the reference JSON has no networking or geography endpoints. Guessed: list paths for static
    MACs (`/networking-service/macAddress/company/{org}` and variants), BSSIDs and switch ports (`RedskyClient._list_first` tries
    several), PUT on the collection path to move a tracking record, DELETE `/geography-service/locations/{id}` and `/buildings/{id}`,
    and the location field on a record (`locationId`, `erlId` or a nested `location`/`erl`). Check these on a real tenant before
    running Remediate. Run against a fake client only (duplicates, both checks, preview and remediation steps).
- Add a tool: a spec in `backend/redsky_*.py`, `class XState(RedskyState, RedskyBulk)` (or `RedskyCheck`) with `SPEC`/`CHECK`
  and `row`, one page function calling `add_page`/`check_page` with the spec object (not `State.SPEC`, which is a Var),
  an entry in `GROUPS` and an `add_page` in `uc_automation.py`.
- Not tested against a real RedSky tenant. The specs were run against a fake client (all add paths, both checks) and the app compiles.

### CUC features

- Menu (`components/cuc_nav.GROUPS`, also the `/cuc` home cards): **Users** (first) = Status Check, Usage Check, Remove Empty;
  **Call Handlers** = Map, Search, Bulk Delete. Same single active connection as CUCM; no multi-cluster mode.
- Port of `cuc/check_userMailbox.py`, `check_userMailboxUsage.py`, `cleanup_emptyMailboxes.py`, `build_call_trees.py`,
  `list_CallHandlers.py`, `list_NonSubscriber_CallHandlers_WithMenuEntries.py`, `delete_CallHandlers.py` (reference only).
- Extensions come from a pasted list or a CSV (first column, header optional). Exports are browser downloads.
- **Status Check, Usage Check and Remove Empty** share one layout (`_three_tabs` in `pages/cuc_users.py`, state mixin `AllRows`): tabs
  All users (first), Paste text and CSV. All users loads automatically when the page opens (10 parallel requests; Reload re-reads) and has a
  search on extension, alias and display name (Contains | Begins with), a checkbox per row and a header checkbox that selects every user the
  search shows. Paste text and CSV look up the extensions you give (first column, header optional) and show their results under the input.
- Status Check and Usage Check: Export selected writes the ticked rows to CSV (status columns, or dtmfAccessID/alias/mailboxSize).
- **Remove Empty** deletes the whole user account (CUC cannot remove only a mailbox). Its All users tab lists only mailboxes with no data;
  Delete selected asks for confirmation, and deletes only ticked users whose mailbox is still empty in the loaded list, then reloads. Paste text and
  CSV keep the scan, review, confirm flow (and Export mailboxes with data).
- **Search** loads every call handler (system and subscriber handlers left out) when the page opens, with the same search, checkboxes and Reload as the
  user pages (state mixin `AllRows`, view `cuc_widgets.all_rows_view`). Export Selected writes the Delete/Map CSV; Export Menu Entries reads the menu
  entries of the ticked handlers (parallel fetch, 10 workers) and writes the second Map CSV, with an errors CSV when some handlers fail. Delete Selected... confirms, deletes the ticked handlers and reloads the list. **Map** builds the call tree xlsx from the live connection or
  from the two Search CSVs. **Bulk Delete** takes ObjectIds (paste) or a List CSV, shows the list, confirms, then deletes (Search also has Delete Selected).
- Tool states are `class X(CucState, CucRun)`; per-row results are shown as failures only (`components/cuc_widgets.failures`).
- Not tested against a real CUC. The backend and the state handlers were run against a local fake vmrest server only.

### UCCX features

- Menu (`components/uccx_nav.GROUPS`, also the `/uccx` home cards): **Migration** = Migrate; **Scripts** = Script Report. Port of the old `uccxTools` scripts
  (reference only, in the untracked `temp/uccxTools`) plus a reader for `.aef` scripts.
- **Migrate** (`/uccx/migrate`, `UccxMigrateState`): origin and destination are two saved UCCX connections of the active organization.
  - **Stored download**: `backend/uccx_store.py` keeps one download in `webui/uccx_download/` (same layout as the old `backup/`: `xml/`, `finesse/`, `scripts/`, `prompts/`, plus `download.json`).
    Every time the page opens and one is stored, a dialog asks to **Continue With It**, **Export As Zip** or **Delete It** (no other way out). It is also deleted automatically after 7 days (`prune`, at app start). A new download replaces it (confirm first). The zip is built in a temp folder and sent by the one-time route `/uccx-export/<token>` (second Starlette app in `api_transformer`), deleted a minute after the download or after 15 minutes.
  - **Download** (`uccx_backup.AREAS`, one result row each): Admin Settings, Application, Call Control Group and Team Details, Prompt Files, Script Files, Finesse Layouts And Codes, Finesse Phone Books, Finesse Team Settings. Folder and file names from the server are checked before they become paths. Documents and grammars are not downloaded (the old script had them commented out).
  - **Upload** (`uccx_restore.STEPS`, run in this order, one result row each): Delete Existing Triggers (off by default), Call Control Groups, Supervisor Role, Skills, Resource Groups, Resources (Agents), Contact Service Queues, Teams, Calendars, Scripts And Prompts, Applications, Triggers, HTTP Triggers, Finesse Call Variable Layouts, Reason Codes, Wrap-Up Codes, Phone Books, Team Settings. A confirm dialog guards it. Things that already exist by name are skipped. A step fails when anything in it failed; the detail names what and the log has every item.
    Options: keep skill IDs (placeholder skills walk the ID counter up), update CSQs/teams/calendars in place by ID (old 6.5, 7.5, 8.5), and the LAN confirmation that call control group import needs. Call control groups that get a new ID are recorded in `ccg-id-map-<server>.json` in the stored download and the Triggers step uses the new IDs.
  - Differences from the old scripts: no prompts or `sys.exit`; XML payloads are built with lxml (names are escaped); missing references on the destination fail or skip that item instead of crashing; a team with a missing primary supervisor is really skipped; endless placeholder loops are bounded; Finesse team files are found from the saved team names, not by parsing file names. The old CUCM clean-up and check scripts (`0_2`, `0_3`) are not ported.
  - Supervisor Role drives the `/appadmin` web pages (form login, CSRF token, user search), the least reliable step. Agents come from CUCM, so Resources only updates agents already on the destination.
- **Script Report** (`/uccx/script-report`, `UccxScriptState`, `backend/uccx_aef.py`): reads `.aef` scripts from the stored download (search, tick, Create Report) or from an upload, and builds one HTML report each (step types and properties in editor order, variables with values, labels with goto counts, author comments). View shows it in a sandboxed iframe, Download gives the `.html` (a zip for several). An `.aef` is a Java serialization stream; the reader needs no Cisco classes and runs nothing from the file (25 MB limit). Property names and the wiring between steps are not resolved.
- Not tested against a real UCCX. The download and upload steps were run against an in-memory fake built from a real old backup (every area and step except Supervisor Role, and Finesse team sub-calls); the script reader ran on one real script.

### Webex login

Webex has no username/password token API, so login is the OAuth authorization code flow with a Webex Integration
(created once at developer.webex.com/my-apps; Redirect URI `http://localhost:3000/webex/callback`).

- Credentials > Webex: paste the Integration's OAuth Authorization URL (Client ID and scopes are parsed from it by `webex_auth.parse_authorization_url`, which also checks the Redirect URI) and the Client Secret, save, then "Log in with Webex". The browser goes to Webex's
  login page and returns to `/webex/callback`, which verifies the one-time `state`, exchanges the code and stores
  `access_token` (about 14 days) and `refresh_token` (about 90 days) in the connection's `[WEBEX:<name>]` section.
- Tokens, the client secret and the refresh token are in `ini_store.SECRET_KEYS`: never sent to the browser.
- The Webex tab (`pages/webex_credentials.py`) has two lists, **Credentials** and **Organizations**; Add/edit open a dialog, delete asks first,
  and each org row has its own credentials dropdown.
- **Logins and orgs are separate** (mix and match): a login is a named `[WEBEX:<name>]` section (Integration and tokens, or a
  pasted bearer token); an org is a named `[WEBEXORG:<name>]` section with `org_id` and `login` (the login it uses). Any login can
  serve any org, and the pairing is changed per org from the Saved orgs list. `webex_auth.resolve(org)` returns `(login, org_id)`;
  `WebexClient.connect(org)` and `check_org(org)` take the **org** name, `ensure_token(login)` takes a login name. The active org is
  `WebexSession.webex_active` (browser LocalStorage, picker in the Webex menu bar; switching reloads the page). `WebexState` is a child
  of `WebexSession` so both lists and the active org are shared. The OAuth `state` remembers which login started it. Older
  `[WEBEX:x]` sections that held an `org_id` are turned into an org `x` using login `x` the first time orgs are listed.
- `/credentials?tab=<cucm|cuc|cube|webex|redsky>` opens that tab; each platform's menu bar login/connection links use it.
- `webex_auth.ensure_token(login)` is what every Webex feature must call before an API request. It checks expiry, confirms the
  token live with `GET /v1/people/me`, and silently refreshes when needed. It raises `WebexAuthError` (message is
  user-ready) when a new login is required. The Credentials page runs the same check on every load.
- Credentials > Webex also takes the customer's **Org ID** (`org_id`, either sign-in method; read it with `webex_auth.get_org_id()`) and
  a switch to **paste a bearer token** instead (`auth_mode=token`, the default and first choice: validated live, no refresh, expiry unknown so it is
  checked with Webex on each use).
- Changing the Client ID drops the stored login. The redirect URI assumes the frontend runs on port 3000.
- Not tested against a real Webex org.

### Webex personal token (403 fallback)

- **Webex Token** in the account menu (top right, next to Change Password) stores the signed-in user's personal bearer token from
  developer.webex.com (about 12 hours) in `.env/webex_personal.json`, one per app user. It is validated with Webex when saved, never
  sent to the browser (backend var `_token`) and never logged; the window shows only status and age. Remove deletes it.
- A 403 from Webex with the org's login is recorded by `WebexClient` (`denied_key`, `webex_api.denied_pending`). Every `webex_page`
  has a hidden 3 second ticker (`WebexSession.poll_denied`); once the task that got the 403 is no longer busy it opens the
  "Webex Denied The Request" dialog. **Switch And Rerun** sets `WebexTokenState.use_personal` (menu bar badge **Personal Token**,
  click it to go back to the org login) and replays the browser event that started the task.
- The rerun works because `TaskRecorder` (middleware) keeps the latest event of every Webex page state and `WebexSession._connect_org`
  marks the one that opened the connection. So it replays button and Paste Text events with their original arguments. CSV file
  uploads do not go through that path: after the switch, upload the file again.
- Webex features must open their client with `self._connect(log)` or `self._connect_org(org, log)` (never `WebexClient.connect`
  directly) so the personal token, the 6 hour check and the 403 offer all apply.
- Right before the personal token is used (`WebexTokenState._personal_token`) it is checked: if it is missing, was saved more than 6 hours
  ago (`webex_personal.STALE_AFTER`) or Webex rejects it (expired), the Webex Token window opens with the reason, and saving a token
  reruns the task.
- Not tested against a real Webex org.

### Webex features

- Menu: `components/webex_nav.GROUPS` drives the Webex menu bar and the `/webex` home cards. Menu order: Call Routing, Locations, Users, Workspaces, Devices, Tools, Reports. Section **Call Routing**:
  Add Numbers (`/webex/add-numbers`, single number plus a CSV | Paste text tab pair for bulk), Call Forward (`/webex/call-forward`, Set or Remove switch) and Gateway Dial Plan (below).
- A feature is backend functions taking a `WebexClient` (`webex_api.py`), a state `class X(_WebexRun)` that builds
  `(label, callable)` items and yields `self._start_run(...)` (per-row results, one log per operation), and a page using
  `webex_page` + `tool_widgets`. Create the client once per run with `self._connect(log)`; never call `ensure_token` per row.
- Every call gets `orgId` from the saved Org ID when there is one. The Locations lookup uses the Calling API
  (`GET /telephony/config/locations`), not the core `/v1/locations` (different scope).
- Call forward owner types: PEOPLE, PLACE, VIRTUAL_LINE (also sets business continuity), HUNT_GROUP, CALL_QUEUE,
  AUTO_ATTENDANT. The forward prefix (default 88888888) is a form field.
- Page states are `class X(WebexSession, RunMixin, ...)`: mixins go on the leaf so busy/results are per page.
  Webex runs do `WEBEX_WORKERS` (4) rows at once (`WebexSession._default_workers`); the result table keeps CSV order, the log lists rows as they finish. Row callables must not touch state.
- **Call Queues** (`/webex/call-queues`): Create (CSV) and Update agents. **Hunt Groups**: Create, Update agents, Migrate to Call
  Queue (Review, then a confirm dialog; the original settings are saved to `webui/logs/<ts>-hunt_group_backup-<name>.json`
  before the hunt group is deleted). **Virtual Lines**: upload a .wav as busy + unanswered greeting. Agents are an email, or a
  number (queue create: virtual line number; hunt group create: extension; hunt group update: virtual line number; queue
  update: email only, as in the scripts). The Calling license check needs `spark-admin:licenses_read` and is skipped when
  the scope is missing. Update agents REPLACES the list and refuses an empty result.
- Create CSVs are header based (`name,location,firstName,lastName,phoneNumber,extension,policy,destination,agent1,agent2,...`),
  unlike the scripts' fixed column positions. The queue create no longer sends the script's hardcoded org-specific announcement
  file id: all greetings are DEFAULT.
- **Users** (Delete Users, Migrate, Reset PIN), **Reports** (Locations Report: `/webex/locations-report`, Run Report, for the ticked Users and/or Workspaces (only those are read; columns, badges and CSV follow), counts Calling users (`GET /people?callingData=true`, a person with a Calling `locationId`) and Calling workspaces (`GET /workspaces?calling=webexCalling`) per location, matched on the decoded location id, with a `(No Location Match)` row, totals and CSV export; not tested against a real org. Voicemail: `/webex/voicemail`, one email or every Calling user of a location via the Add Numbers style location datalist; reads `GET /people/{id}/features/voicemail`, shows internal/external and, for external, the destination email; internal message counts are not available to an admin login), **Workspaces** (Add Workspace, Copy Workspace, Add Device), **Locations** (Schedules, E911) are menu groups
  in `webex_nav.GROUPS`. Destructive actions (delete users, migrate, copy/update/remove schedule events, RedSky opt-out) go
  through `tool_widgets.confirm_dialog` (`S.confirm_open`). Delete Users and Migrate are two-step: load/review a plan first,
  then confirm.
- Add Workspace (`/webex/create-workspace`, `CreateWorkspaceState`): Single Workspace form or Multiple Workspaces (Paste Text / CSV;
  columns workspace, location, type, capacity, number, extension, model, mac, license). The optional **license** (a Calling License select on the single form, a column in paste/CSV: Professional Workspace or Common Area Workspace, validated by `normalize_license`) sets `calling.webexCalling.licenses` to the matching `GET /licenses` ids (`workspace_license_ids`) and needs a number or extension and a location; blank leaves the choice to Webex. `POST /workspaces`; optional Device Model (supported-models datalist and info popover, loaded on page load through the mixin hook `_load_extra`) and MAC together also `POST /devices` on the new workspace (model and mac must both be given; a device failure is reported on the row with the workspace already created); a number or extension adds Webex Calling
  at the location (`supportedDevices` phones). Single and multiple: before creating, a workspace name that already exists (or repeats in the batch) is skipped with a warning, and rows with a location and
  a number are checked (`review_row_number`). Numbers not configured anywhere prompt to add them to the location first (DID, active,
  unused); a number that is already assigned (shows what it is in use on) or belongs to a different location is never added, its workspace is skipped and shown as failed. Not tested against a real org.
- Copy Workspace (`/webex/copy-workspace`, `CopyWorkspaceState`): one existing workspace (name, optional location) is the template;
  Single Copy or Multiple Copies (Paste Text / CSV; columns workspace, location, number, extension) create new workspaces with its
  type, capacity, notes, hotdesking status, location and (when the source has Webex Calling and the copy gets a number or extension) its calling settings (`CALLING_SETTINGS`: call forwarding, waiting, caller ID, permissions, intercept, recording, voicemail, DND, ring and selective features; each is a GET on the source then a PUT on the copy, failures are listed in the row detail and do not fail the workspace; numbers, emergency callback number, devices, monitoring, audio greetings and criteria lists are not copied). Numbers and extensions are never copied; without a location a
  number or extension uses the source's Webex Calling location. Shares the name and number review, confirm dialog and run with Add
  Workspace through `WorkspaceCreateMixin`. Not tested against a real org.
- Get Workspace (`/webex/get-workspace`, `GetWorkspaceState`, menu group **Workspaces**, `backend/webex_workspaces.get_workspace_details`): search a workspace by name (optional location), Get Workspace shows a summary table (location, calling type, calling location, calling license names resolved from `GET /licenses`, number, extension, type, capacity, hot desking, notes), then each calling setting as JSON (`CALLING_SETTINGS` plus `EXTRA_SETTINGS`: numbers, emergency callback number, devices, monitoring) and the raw workspace record. Settings that cannot be read are listed in a callout. Read only. Not tested against a real org.
- Upgrade Calling License (`/webex/upgrade-license`, `UpgradeLicenseState`, menu group **Workspaces**, `backend/webex_workspaces.upgrade_license`): one way only, Common Area Workspace to Professional Workspace (no downgrade), so there is no license selector. One Workspace (search by name, optional location) or Multiple Workspaces (Paste Text / CSV `workspace,location`). The license ids come from `GET /licenses`, classified by name (`license_kind`: Professional Workspace is the same license as a user, `Webex Calling - Professional` (confirmed); Common Area is any name containing "common" or "workspace", its exact name is unverified). Per workspace: `GET /workspaces/{id}`, must be `webexCalling`, skipped with "Already has" when it already has the Professional license, else a full `PUT /workspaces/{id}` (displayName, type, capacity, notes, hotdeskingStatus sent back) with `calling.webexCalling` locationId, licenses, and the existing phoneNumber and extension. Not tested against a real org.
- Add Device: `AddDevicesWorkspaces.py` is an unfinished draft (it never runs the CSV loop), so the page implements its
  intent: add a device (`POST /v1/devices`: model, MAC, workspace) to an existing workspace found by display name. CSV is
  `workspace,model,mac[,location]`. It does not create workspaces. An info popover beside Model lists the org's
  supported models (`GET /telephony/config/supportedDevices`, loaded on page load): the model text to import and the display name.
- Bulk ATA/VG (`/webex/bulk-ata`, `BulkAtaState` in `state/webex_devices.py`, menu group **Devices**): one form (location, model, MAC, one line per port: workspace, extension, optional number) or Paste Text / CSV with one line per port (`mac,model,location,workspace,extension,number`; the same MAC groups ports into one device, file order is port order). Per device (`add_ata`): everything is checked first (names unique and not existing, extension or number per port), then a Webex Calling workspace per port (`POST /workspaces`), `POST /devices` on the first workspace, and `PUT /telephony/config/devices/{id}/members` with workspace n on port n (port 1 primary owner). A failure part way leaves what was already created. Not tested against a real org. A third tab, **Update ATA Or VG**: a search box (datalist of the org's ATA/VG devices, product matching ATA, VG or DMS) loads the device's ports (`GET /telephony/config/devices/{id}/members`, `maxLineCount` gives the port count). Each port shows its workspace and line; an open port can be given an Existing workspace (search list) or a New one (extension or number, created in the location of the device's workspace). `update_ata` checks everything first, then PUTs the members list with the current members sent back unchanged, and the ports are re-read afterwards. A new workspace whose number is not in the location gets the number added and is retried (`create_workspace_adding_number`, shared with the CUCM gateway migrate). After the ports are assigned, `ATA/VG <device label> port <n>` is appended as a new line to each assigned workspace's notes (`append_port_note`: GET then PUT with displayName and notes only; a failure is reported in the result, not raised). Run logs as Update ATA/VG. A fourth tab, **Find Port**: a search box (workspace name through `GET /workspaces?displayName=`, digits also as an extension and, from 10 digits, a phone number through `GET /telephony/config/numbers?ownerType=PLACE`) lists matching workspaces; **Show Gateway** finds the ATA/VG the workspace is on (`find_ata_for_workspace`: the workspace's `/telephony/config/workspaces/{id}/devices` matched by MAC, else every gateway's members are read) and loads its ports into the same table as the Update tab, with the found port highlighted. The dropdown label carries the location (`list_ata_devices`); telephony calls use the device's `callingDeviceId`. Not tested against a real org.
- Webex-Webex Phone Migrate (`/webex/webex-phone-migrate`, `DeviceMigrateState`, menu group **Devices**, `backend/webex_devices.py`): the menu bar hides the Org and Instance selectors and the "Login" and "Logged in" badges (`webex_page(show_org=False)`, the Org is picked on each card), and there are two side-by-side cards, left and right, each with Org (with a badge beside it showing that org's login: Checking, Logged in or Login required, rechecked on page load and whenever the org changes; `DeviceMigrateState.login_l/login_r`), User and MAC (all kept in browser LocalStorage), and two arrow buttons between them. An arrow moves the phone with the MAC of the side it leaves to the User of the side it points to; the source side's User is an optional ownership check. After a successful single move the MAC shows on the destination side and is cleared on the source side. A multiple-phones card (Paste Text / CSV `mac,user`, direction chosen with a segmented control) moves left to right or right to left. Both go through a confirm dialog. Per phone (`migrate_phone`): find it in the source (`GET /devices?mac=`), read its model (`GET /telephony/config/devices/{id}`), map it to a destination supported model, check the MAC is not already in the destination and the user exists (`GET /people` by email or exact display name), then `DELETE /devices/{id}` in the source and `POST /devices` (mac, model, personId) in the destination (3 tries, 4 s apart, as the MAC can take a moment to be released). If the add fails the phone is added back to its source workspace or person. Calling settings and numbers do not move, and the phone needs a factory reset afterwards. Not tested against a real org.
- CUCM-Webex Phone Migrate (`/webex/cucm-phone-migrate`, `CucmMigrateState`, menu group **Devices**, `backend/webex_cucm_migrate.py`): same two-card layout as Webex-Webex Phone Migrate; left is a saved CUCM connection, a CUCM user ID and a MAC, right is a Webex org, a Webex user and a MAC (kept in LocalStorage). Right arrow (`cucm_to_webex`): `getPhone SEP<MAC>` must succeed (optional owner check against `ownerUserName`), the model maps to a Webex supported model, the MAC must not be in the org, the Webex user is found, then `POST /devices` (mac, model, personId). The CUCM phone is kept. Left arrow (`webex_to_cucm`): the phone configuration must already exist in CUCM (nothing is added to CUCM), then `DELETE /devices/{id}` in Webex, with optional owner checks on both sides. A multiple-phones card (`mac,user`, direction segmented control) does the same in bulk; confirm dialog first. Going to Webex the phone needs a factory reset. Going to CUCM it must still be converted to Enterprise firmware by hand: the result text (`M2E_STEPS`) gives the phone's `/admin/advanced` > Voice > Provisioning Profile Rule `https://cloudupgrader.webex.com/Cisco/M2E/$SWVER/$PN/$MA.cfg`; the app does not reach the phone. Not tested against a real CUCM or org.
- CUCM-Webex Analog Gateway Migrate (`/webex/cucm-gateway-migrate`, `CucmGatewayState`, menu group **Devices**, `backend/webex_cucm_gateway.py`): pick a saved CUCM connection and a gateway name (List shows analog gateways via `listGateway`; an SCCP name `AN<MAC>` also fills the MAC), Read Gateway lists the ports (`executeSQLQuery` on `device` joined to the first line DN and partition, matching the gateway's hex name because a VG350 `SKIGW<hex>` has ports named `AN<hex>nnn`; `getGatewayEndpointAnalogAccess` per endpoint, kept only when its `domainName` is the gateway; port = endpoint `index` + 1; verified against a VG350 on slab42-cucm2). The ports table is editable: Create checkbox (port 1 always on, other ports with a DN are ticked), port, workspace name, extension or number (a `+` or 10+ digits is a number). Then a Webex location and a **Device** segmented control: **Add Device Now** (model and MAC required) or **Add Device Later**. `migrate_gateway` checks everything first, creates a Calling workspace per ticked port, and for Now also `POST /devices` on the port 1 workspace plus `PUT /telephony/config/devices/{id}/members` (workspace on its own port number) when more than one port; Later stops after the workspaces and tells the user to add the device with Add Device. When creating a workspace with a phone number fails, the number is added to the location (`add_location_number`, DID, active, unused) and the workspace is created again once; the result lists the numbers added. A **Use an existing workspace** checkbox (off by default) assigns a workspace that already has the name to its port as it is (`find_workspace_id`, nothing changed on it) instead of stopping the run. Nothing is changed in CUCM. Reading ports was checked on one CUCM; creating in Webex was not tested against a real org.
- Migrate moves users (PRIMARY number, owner type PEOPLE) with the Move Users job (validate, run, poll up to 180 s).
  Workspaces are skipped: the API cannot change a workspace location.
- Schedules (one page, four modes): Export (CSV download), Update from CSV (review plan, then apply), Copy (to all other
  locations or one), Remove past events (one-time holiday events ended before today; tick what to delete). Locations come from
  the Calling API. E911: status table (2 calls per location, 5 in parallel), export, and opt-out of ticked locations (tick by
  hand or from a CSV of names).
- **Locations > Copy Location** (`/webex/copy-location`, `CopyLocationState`, **in development**: in `webex_nav.IN_DEVELOPMENT`, amber menu badge, hidden unless the experimental setting is on, callout on the page; the core `POST /locations` call returned 403 for the partner login tested, `backend/webex_locations.copy_location`): pick a source location (the list also shows each location's PSTN connection, `GET /telephony/pstn/locations/{id}/connection`, 5 reads in parallel, "Unknown" when one fails), enter the new name (max 80 characters, must not exist) and optionally override the address. One run: `GET /locations/{id}` (time zone, languages, address, coordinates, notes), `POST /locations`, then `POST /telephony/config/locations` to enable Webex Calling. Optional checkboxes copy the calling settings (`externalCallerIdName`, `outsideDialDigit`, `enforceOutsideDialDigit`, `pAccessNetworkInfo`, `useChargeNumberForPChargeInfo`, GET on the source then PUT on the copy) and the schedules (`copy_schedule_to`); a failure there is noted in the row detail and does not fail the copy. Numbers, users, devices, routing prefix and PSTN connection are never copied. If enabling Webex Calling fails the new core location stays and the message says so. Not tested against a real org.
- **Call Routing > Gateway Dial Plan** (`/webex/gateway-dial-plan`, `GatewayDialPlanState`, `backend/webex_dialplan.py`): Add Dial Plan and Edit Dial Plan tabs. Add: name, route (trunk or route group, from `/telephony/config/premisePstn/trunks` and `routeGroups`) and dial patterns (Paste Text first, or CSV, first column under a header row) become a `POST /telephony/config/premisePstn/dialPlans`. Edit: pick a dial plan (`GET .../dialPlans`), see its patterns (`GET .../dialPlans/{id}/dialPatterns`) and add more (`PUT` with `action: ADD`, 50 per call, patterns already on the plan are skipped). Dial plans are org wide, not per location. The pattern list has a search box (narrows the list), checkboxes, Select Matching (ticks every pattern the search matches) and Select None; Delete Selected (confirm dialog) sends `PUT` with `action: DELETE`, 50 per call. At most 300 patterns are listed at once, search to narrow. Needs `spark-admin:telephony_config_read/write`. Not tested against a real org.
- **Locations > Migrate PSTN** (`/webex/migrate-pstn`, `MigratePstnState`, `backend/webex_locations.py`): pick a location; it shows the current connection (`GET /telephony/pstn/locations/{id}/connection`) and offers trunks, route groups (`/telephony/config/premisePstn/trunks`, `routeGroups`) and the cloud connection options (`.../connectionOptions`, premises option skipped, plus the NON_INTEGRATED_CCP connections any other location already uses, read once per page load, because the options endpoint is per location and can omit a provider) as the new connection. Migrate (confirm dialog) is a `PUT` on the connection: `premiseRouteType` + `premiseRouteId` for a trunk or route group, `id` for a cloud option. Integrated CCP and Cisco PSTN cannot be set through the API. The current connection is always offered too. **Migrate PSTN has Single Location and Multiple Locations tabs. The Multiple Locations tab: paste location names (Paste Text first) or a CSV, Find Locations matches them (names case-insensitive, unmatched ones are listed) and reads the connection options of the first matched location, then one new connection is applied to all of them (one `PUT` each, per-row results). Needs the `spark-admin:telephony_pstn_read/write` scopes. Not tested against a real org.
- **Tools > Naming Check** (`/webex/naming-check`, `NamingCheckState`, `backend/webex_naming.py`; **in development**; Rules and Regex tabs, the Regex tab turns a plain-English description into a regex with `describe_to_regex` (fixed phrase rules, no AI. Sequence mode: ordered steps like "location name, a space, then 5 letters" become one anchored regex (`_sequence_regex`); otherwise rule mode: starts/ends with, contains, allowed characters, no spaces, length) with a copy button, a Use As Rule button and the same quick reference as the info popover: `webex_nav.IN_DEVELOPMENT` puts an amber badge on its menu item and the page shows a callout; remove the route from that set when it is finished): one regex per item type (locations, call queues, hunt groups, auto attendants, workspaces, virtual lines; empty skips the type) with a hints select per row (`HINTS`) and an info popover beside the Rules heading (`_REGEX_HELP` in `pages/webex_naming.py`: anchors, wildcards, brackets, shortcuts); `{location}` in a regex expands to the item's escaped location name. Run Check lists the items and shows PASS/FAIL with a CSV export. A suggested name for each failure comes from the optional find/replace regex, else from automatic fixes (`suggest`: spacing, odd characters, case variants plus the rule's literal prefix/suffix, first candidate that passes); it is kept only if it changes the name, fits `MAX_LEN` (30 characters for queues, hunt groups and auto attendants, Webex rejects longer) and passes the rule, and the Suggested Name cell is editable (red when it does not pass; `valid` marks renamable rows); Rename Suggested (confirm dialog) renames those: `PUT /locations/{id}` (name), `/workspaces/{id}` (displayName), `/telephony/config/virtualLines/{id}` (displayName), and `/telephony/config/locations/{loc}/{queues|huntGroups|autoAttendants}/{id}` (name). Not tested against a real org.
- **Tools > Check Hardware Compatibility** (`/webex/hardware-compatibility`): one phone or a CSV (`model,mac`). Model is checked
  against `GET /telephony/config/supportedDevices` (model code or display name), MACs against `validateMacs` in batches of 50
  (a write-scoped call that only validates). Status VALID / WARNING / INVALID with a reason; results export as CSV. The
  model box suggests the supported models.
- Request shapes come from the Webex docs; not tested against a real Webex org.

## Adding a new CRUD resource (the normal case)

Example: a new CUCM object "Foo" with name and description.

1. **Backend** (`backend/cucm_<area>.py`). Write `list_foos`, `add_foo`, `update_foo`, `remove_foo`.
   - List with `list_paged(conn, "listFoo", "foo", {"name": "%"}, ["name", "description"])`.
     It pages 500 at a time (AXL rejects unpaged lists over 1000 rows) and unwraps reference fields.
   - Wrap other calls with `_call(conn, "addFoo", foo={...})`, which turns zeep faults into `AxlError`.
   - Raise `AxlError("plain message")` for validation problems. The UI shows the message as is.
2. **State** (`state/<area>.py`). Define a `ResourceSpec` (noun, key field, fields, CSV templates, the
   four functions, add-form defaults) and the class:
   ```python
   class FoosState(CucmState, CrudMixin):
       def _spec(self) -> ResourceSpec:
           return FOO_SPEC
   ```
3. **Page** (`pages/<area>.py`). `build_crud_page(FoosState, CrudPageConfig(title=..., noun=..., key=...,
   columns=[Column("Name", "name", code=True), ...], add_body=<function building the add form>))`.
   Form helpers: `form_field(label, control)`, `text_input(S, field)`.
4. **Route + menu**. `app.add_page(page, route=..., on_load=FoosState.on_page_load)` in
   `uc_automation.py`, and one line in `GROUPS` in `components/cucm_nav.py` (the CUCM home cards follow).
5. **Verify** (see Testing below).

You get search, per-row checkboxes, select-all, delete selected, bulk delete from CSV, export (all or
selected), add, import with Add/Modify, result tables, and the connection picker for free.

`CrudPageConfig.import_add=False` hides the import dialog's Add button, and `modify_label` renames the button that runs
`update_fn`. Action pages (Directory Numbers > Move Partition, Alternate Numbers) use both so import means "Move" /
"Remove alternate numbers". Orphans finds DNs with pattern usage 2 (Device) and no `devicenumplanmap` row; the usage
number and SQL are unverified, so test on a lab CUCM.

### CUCM Reports

- **Reports > Device Report** (`/cucm/device-report`): All Device Pools or Search (name contains). Per pool: Registered, Unregistered, Total Devices, Gateways, plus a totals row and CSV export. **Consolidate Device Pools** (Off, Prefix, Regex) merges pools sharing a key and sums the counts, adds a Pools column, and works on the stored raw rows (`raw_rows`, `report_rows` is computed) so changing it does not re-query. Prefix: first N parts split on a delimiter plus the trailing delimiter (`AGY-SITE-`); Regex: first capture group or whole match (`pool_group_key`, `consolidate_rows` in `backend/cucm_reports.py`). Names that do not fit stay on their own. Device checkboxes (Phones, Analog Phones, CTI Devices, Gateways) and Pull Registration choose what is queried: only selected kinds are read, RisPort70 is skipped when registration is off or only gateways are selected (registered and unregistered columns are then blank). Phones come from one SQL query on `device` joined to `typemodel` (kind by model name), registration from RisPort70 `selectCmDevice` by name in batches of 1000, paced 4.2 s apart per server (RisPort70 allows 15 requests per minute); a rate fault is retried after 60 s up to 3 times, and if it still fails after the first batch the report keeps the partial Registered counts, blanks Unregistered and shows an amber warning; progress (batch n of N) shows on the page and in the log (`https://<server>:8443/realtimeservice2/services/RISService70`, the AXL account needs the Standard RealtimeAndTraceCollection role; anything not reported Registered counts as unregistered), gateways from SQL (`device` joined to `devicepool` and `typeclass` where the class name is `Gateway`, all gateway types). Not tested against a real CUCM; the RIS request and the typeclass name are unverified.
- **Devices > Device Export for Webex** (`/cucm/device-export-webex`): Find Device Pools (name contains, blank lists all), tick one or more, optional Pull Registration Status (RisPort70, reuses `cucm_reports.registered_names`), Run Export, Download Excel (`device-pool-export-<server>-<stamp>.xlsx`, bytes kept in backend var `_xlsx`). Phones come from SQL (`device`, `devicepool`, `typemodel`), the rest from `getPhone` per phone (4 threads): protocol, description, template, Owner User ID, lines (index, DN, partition, display, label, e164 mask, ASCII display = Caller ID, associated end users) and BLFs. End users come from SQL (`enduser`, `enduserdevicemap`, primary extension `fknumplan_primary`). Owner order (`resolve_owner`, column Owner Source): Device Owner, Associated Device, Line (line associated end users, then primary extension match). When no owner is found, `guess_user` matches the phone description, then the line 1 description, then the line 1 display name against user IDs (a word equal to the ID) and first/last name pairs (either order), accepting only a single match; Owner Source is `Guess: <source>` and the User ID, First Name, Last Name and Email cells are filled yellow. Email falls back to the end user's directory URI when Mail ID is empty. Type is `User` when any user is found, otherwise `Workspace`; extra users go in Notes. Workbook sheets: **Phones** (one row per device, `Line N DN/Partition/Display/Label/External Mask/Caller ID` columns up to the highest line index, so KEM/sidecar lines are included by index), **BLFs**, **Summary**, **Errors**. `build_workbook(result, extra_sheets)` takes more sheets, for the planned Hunt Groups sheet. The same workbook is meant as the input of a later Webex build tool. **In development** (`IN_DEVELOPMENT`). Not tested against a real CUCM: the SQL table and column names (`enduserdevicemap`, `fknumplan_primary`) and the getPhone shapes (checked against the XSD only) are unverified; BLF destination partition is not read.

### CUCM Call Routing > SME Adv & Route Patterns

- `/cucm/sme-adv-route-patterns`, `SmePatternsState`, `backend/cucm_sme_patterns.py`. Port of `uc-automation/cucm/AdvP_RP_add.py`: for each number it adds an Advertised Pattern (`addAdvertisedPatterns`) and a Route Pattern (`addRoutePattern`), reusing `cucm_routing.add_advertised_pattern` and `add_route_pattern`. Both are tried; a row fails if either fails and the detail names which. 10 digit numbers become `+1...` (Advertised) and `\+1...` (Route Pattern), as in the script.
- **SME only, no instance picker**: the page hides the Instance selector (`show_instance=False`) and always runs on the organization's SME cluster (the first connection of the active organization with the SME cluster box ticked, `sme_selected`, same as Webex Cutover step 3). `require_sme` still refuses a missing or non-SME connection. The page shows a red callout when the organization has no SME cluster.
- Inputs: One Pattern (pattern plus one input per variable, labelled with the variable's name (`Var1` when the name is blank)) and Multiple Patterns (Paste Text first, CSV second; columns `pattern` then one per variable (the tab shows the variable names, `var_display`; a header may use the name or Var1 to Var9, any case, variable columns optional); the One Pattern inputs are the defaults for missing values).
- **Settings window** (gear button, top right of the page body; kept in browser LocalStorage `sme_*`): the Cluster section only shows the organization's SME cluster and an SME badge (no typing); **Variables** (above the Advertise section; `var_names_json`, LocalStorage `sme_var_names`): Var1 with a Name (default Department) and a plus (Add Variable, up to 9, Var2, Var3...) each with its own Name and a remove button (later ones move up, and the `{VarN}` in both descriptions are renumbered the same way: the deleted variable's placeholder is dropped, `renumber_template`). Advertise Pattern Settings (description template, Enterprise Number or +E164 Number pattern, PSTN setting: No PSTN / Use pattern / Specify with PSTN Failover Strip and Prepend Digits); Route Pattern Settings (description template, route partition, Route List or Gateway name). Description templates take `{Var1}` to `{Var9}` (any case, never the variable's name) and `{Pattern}` (last 10 digits); other `{names}` are rejected, and a variable used in a template needs a value for every row. The default templates use `{Var1}`. Defaults are the script's constants. Reset To Defaults restores them.
- Logged as "SME add Advertised and Route Pattern(s)" with the connection, the settings and per-row results. Not tested against a real CUCM; request shapes were checked with zeep `create_message` on 12.5 and 15.0 and the description, number and CSV helpers were run on sample data.

### CUCM Migration > Webex Cutover

- `/cucm/webex-cutover`, `CutoverState`, `backend/cucm_cutover.py`, menu **Migration**. Input: a list of DNs (Paste Text first, CSV second; the CSV fills the Paste Text box so every button reads the same list). One DN per line, optional partition second, header optional; a blank partition takes the **Default Partition** from the Settings window (gear, LocalStorage `cut_*`). Device names are not supported yet.
- Three separate buttons, each runs only its own step on every DN: **1. Remove Alt Numbers** (`cucm_dn.remove_alt_numbers`, confirm dialog), **2. Move Partition** (`cucm_dn.move_dn` to the Destination Partition from Settings, confirm dialog), **3. SME Add AdvP-RP** (`cucm_sme_patterns.add_pattern_pair`).
- Steps 1 and 2 run on the active connection. Step 3 runs on the organization's SME cluster (the first SME connection, shown in Settings, nothing to pick). The Settings window holds the same SME settings as SME Adv & Route Patterns (`SmeSettingsMixin`, same browser keys `sme_*`, so editing on either page changes both): variables, Advertise Pattern and Route Pattern settings. A value is asked for each variable the descriptions use, applied to every DN.
- **Variable regex**: each variable has an optional regex in Settings (`sme_var_regex`, one per variable, kept in step when variables are removed). The value typed for it must match (`re.search`: anchor with `^` and `$` for the whole value); a failing value shows a red message under its field and the run (cutover step 3, and SME Adv & Route Patterns for the page and per-row values) stops with an error before anything is added. An invalid regex is a settings error.
- **Number Length** (next to Prefix Pattern, `number_length`, digits only, blank = off): keeps that many characters from the right of each DN before the prefix is added (`42065266095`, length 10, prefix `+1` gives `+12065266095`); a shorter DN is kept whole.
- **Prefix Pattern** (input above the tabs, `prefix`, not stored): put in front of every DN in the list before any step runs (skipped when the DN already starts with it), e.g. `+1` turns 10 digit numbers into `+1` plus 10 digits. A DN starting with `+` is looked up in steps 1 and 2 as `\+...` (`cucm_cutover.dn_key`), the Route Pattern gets a `\` in front (`format_route_pattern`, any `+`), the Advertised Pattern keeps the plain `+`.
- **Step 3** reports each pattern on its own: `Advertised pattern: added X; Route pattern: added Y in <partition>` (or `failed ... (<error>)`; any failure marks the row failed, SME Adv & Route Patterns shows the same text). It first looks for the Route Pattern (`cucm_routing.find_route_pattern`); when it exists it is not added and its pattern and description are reported. The checkbox "If the Route Pattern already exists, add the Advertised Pattern anyway" (`adv_anyway`, off by default) decides whether the Advertised Pattern is still added. SME Adv & Route Patterns does not do this check.
- Each step is its own log ("Cutover ..."). Not tested against a real CUCM; the list parser was run on sample text and the app compiles.

### CUCM Migration > Cutover Cleanup

- `/cucm/cutover-cleanup`, `CleanupState`, `backend/cucm_cleanup.py`, menu **Migration**. Two inputs, each Paste Text first and CSV second (the CSV fills the box): **Directory Numbers** (same format as Webex Cutover; a DN without a partition matches that number in any partition) and **Device Names** (one per line, commas or spaces also separate, a 12 digit MAC becomes `SEP<MAC>`, header optional).
- **1. Delete Devices And Orphan DNs** (confirm): per device `getPhone` lines, `removePhone`, then each of its DNs that no device, profile or remote destination profile uses (`removeLine`). Devices run first, one at a time, then the listed DNs (orphans only; a DN already removed with its device reports "Not found"). Only phones are removed.
- **2. Remediate Hunt Groups**: lists line groups (`listLineGroup` + `getLineGroup`, 4 threads) with any listed DN as a member, with matched DNs, member count and hunt lists. Tick groups, then **Remove DNs From Line Groups** (`updateLineGroup removeMembers`; refused when every member is in the list) or **Delete Line Groups** (refused while a hunt list uses the group). Use Hunt Groups to remove pilots and hunt lists.
- **3 to 9** (Call Pickup Group, Common Device Configuration, Phone Button Template, Softkey Template, Partitions, Calling Search Space, Device Pool): one shared search box (name contains, blank = all, Device Pool requires text) and one list panel. Each row is Unused, In use or Unconfirmed (Call Pickup Group and Phone Button Template hide In use rows, `HIDE_IN_USE`); only Unused rows can be ticked; **Delete Selected** (confirm) uses the AXL remove call, which CUCM still refuses for anything in use. Pickup groups and phone button templates reuse `find_*_usage`. Common device configs, device pools, softkey templates, partitions and CSSs (`_fk_usage`) read every table with a column starting `fkcommondeviceconfig`, `fkdevicepool`, `fksoftkeytemplate`, `fkroutepartition` or `fkcallingsearchspace` from `systables`/`syscolumns` and count references per pkid (the object's own tables, `softkeyset` and the CDR tables `cdr_*`, `cmr_*` are skipped).
- **In development** (`IN_DEVELOPMENT`: hidden unless Settings > experimental is on, amber callout first on the page). Every scan and delete is its own log ("Cleanup ..."). Results and lists are in `output_fields`. Not tested against a real CUCM: the SQL (`systables`, `syscolumns`, `numplan`, `devicenumplanmap`, table names `callingsearchspace`, `softkeytemplate`) and the `getPhone`/`getLineGroup`/`updateLineGroup` shapes (the last checked against the XSD only) are unverified. The parsers and the foreign key scan were run on sample data and the app compiles.

### Objects identified by pattern + partition

Route patterns, translation patterns and hunt pilots are only unique per partition. Give the `ResourceSpec`
`key="id"` and `key_parts=("pattern", "routePartitionName")`. Rows then get an `id` (parts joined with `|`,
`backend/keys.py`) that drives selection, delete targets and result rows; results show "9.911 in PT-A". `remove_fn`
receives the id (use `split_key`). CSVs need only the first key part as a required header. Set
`CrudPageConfig.add_required` to the field that enables the Add button (for example `pattern`). Examples:
`state/route_patterns.py`, `state/translation_patterns.py`, `state/hunt_groups.py`.

### Delete with cleanup

`remove_fn` may return a string, which becomes the result detail. CTI route points and hunt pilots use this: after
the object is removed they also remove what is left unused (DNs on no device; hunt list and line groups no other
pilot or hunt list uses) and report each step. A cleanup failure is noted in the detail and does not fail the removal.
System pages (`pages/system.py`) hide built in objects the scripts skip (region Default; locations Phantom, Shadow,
Hub_None). Their dependency checks (`find_region_usage`, `find_location_usage`, `find_device_pool_usage`) join each
candidate table to the referenced table by `fk<table>`; a table or column missing on a release is skipped, any other
SQL error becomes a warning (status Unconfirmed). Regions cannot be modified: AXL `updateRegion` has no `defaultCodec`.
Cleanup needs `executeSQLQuery` (`cucm_axl.sql_rows`, AXL has no call for "which devices use this DN"). SQL is
is the least verified part, so test it on a lab CUCM.

### Dependency check (`DepCheckMixin`)

For resources CUCM refuses to delete while in use (phone button templates, call pickup groups): add
`DepCheckMixin` to the state, implement `_dep_fn()` returning `(conn, names) -> ({name: [refs]}, warnings)`, and use
`dependency_toolbar` / `dependency_dialogs` from `components/crud_page.py` as `extra_toolbar` / `extra_dialogs`.
Examples: `PickupGroupsState`, `PhoneButtonTemplatesState`, `HuntGroupsState` (line groups that still have members).

### Config flags (`CrudPageConfig`)

`can_add`, `can_import`, `can_modify`, `can_delete` hide the matching buttons. `can_copy` (off by default) adds a
Copy button: with one row selected it opens the Add dialog pre-filled from that row (Advertised Patterns, Route Patterns, Translation Patterns and CTI Route Points use it). `delete_note` adds text to the
delete confirmation. `import_notes` adds text under the import template.

### Custom actions on top of the shared page

Use `extra_toolbar` (returns buttons) and `extra_dialogs` (returns dialogs, receives helpers `dialog`,
`close_button`, `results`, `progress`, `dropzone`, `code_block`). Examples to copy:

- **Dependency check** on Phone Button Templates: `PhoneButtonTemplatesState.check_dependencies`
  and `_pbt_toolbar` / `_pbt_dialogs` in `pages/devices.py`.
- **Firmware workflow** (not CRUD) on Physical Phones (MPP): `MppPhonesState` with `can_*` all off.
  It reuses select and the per-row results runner. It lists nothing until Search is pressed
  (`CrudPageConfig.search_first`, `run_search`: name or description contains the text, or the Device Pool option for the pool name, queried from CUCM).
  The page has two tabs (`CrudPageConfig.wrap_body`): Search, and Bulk, which takes Paste Text (default) or CSV (fills the paste box) with inline results; `cucm_cleanup.parse_devices` accepts
  device names with or without SEP and MAC addresses in any format.
  The Active Load ID column comes from RisPort70 (`cucm_reports.active_loads`, registered phones only, blank on failure); Load Override is AXL `loadInformation`.

Dialogs are driven by one string var, `dialog` (`""`, `"add"`, `"import"`, `"bulk"`, `"confirm"`,
`"result"`, `"exportchoice"`, or your own name). Open with `S.set_dialog("name", True)`.

## Tool pages (not CRUD)

CUCM > Tools (`pages/tools.py`, `state/tools.py`, `components/tool_widgets.py`) are one-off runners, not lists.
`RunMixin` gives them busy / progress / per-row results and `_start_run`, which runs each item in a thread and logs it.
Their routes are registered with `on_load=<State>.load_connections`. Secrets: PINs come from a password input (backend
var) or an uploaded CSV, go straight to CUCM or the EM servlet, and are never logged or shown. EM login and logout call
`http://<server>:8080/emapp/EMAppServlet` from the app's host, so that host must be able to reach the EM server.

## Shared behavior worth knowing

- **Bulk runs are background tasks.** A handler builds `(label, fn)` items (or `(label, fn, extra_fields)`) and
  yields `self._start_run(items, verb, log, then="_after_x")`, then returns. `run_job` (background) runs them
  `workers` at a time in threads and updates progress and results under `async with self`, so the tab stays usable.
  `run_progress` (in `run_results` and the CRUD dialogs) shows a Cancel button (`cancel_run`): no new items start,
  running ones finish. Item callables must not touch state. Work that follows the run goes in the sync
  `then` method `(self, log)`, called under the lock with final results; it may return events (toasts, `type(self).fetch`,
  or another `_start_run` to chain a second run on the same log). Run handlers start with `if self.busy: return`.
- `CrudMixin._start_each(conn, targets, op, verb, done, log, then)` does that for `op(conn, target)`; rows carry the
  target `id`. If `op` returns a non-empty string it becomes that row's detail.
- Confirm dialog actions start with `if not self.<open var> or self.busy: return` and close the dialog before any
  await, so a queued second click is ignored.
- Page state lives in memory (`state_manager_mode="memory"` in `rxconfig.py`): the disk mode pickled backend vars,
  passwords included, into `.states/`. A backend restart drops open page state.
- Lists render the first 500 filtered rows (`DISPLAY_LIMIT` in `state/crud.py`). Search, select-all and
  export cover every match.
- Export with rows selected asks for Selected or All. Without a selection it exports all.
- Import: header row required, only the key column is required, extra columns ignored, column names
  case-insensitive. Add uses defaults for blank cells. Modify leaves blank cells unchanged.
- Bulk delete and import report success or failure per row. One failure never stops the rest.

## Pitfalls we hit (do not relearn these)

- **Generator handlers cannot `return value`.** If a handler has any `yield`, write `yield rx.toast.error(..)`
  then a bare `return`.
- **Mixins cannot name the concrete state class.** Shared helpers are plain `async def` generators
  (`_fetch`, `_import`) that handlers forward with `async for ev in self._x(): yield ev`.
  Do not call one event handler from another. Subclasses supply behavior through `_spec()`.
- **`rx.upload_files(...)` takes exactly one handler argument.** Two actions on one upload (Add and Modify)
  need two handlers (`import_add`, `import_modify`).
- **State vars must be JSON-friendly.** Use `list[dict[str, str]]`, plain strings, ints, bools. Convert in the
  backend (`_text()` in `cucm_axl.py` flattens AXL reference fields like `{'_value_1': name, 'uuid': ..}`).
- **No auto setters.** Write explicit handlers (`set_search`, `set_new`). Per-field forms use one dict var
  (`new_form`) and `lambda v: S.set_new("field", v)`.
- **`rx.text(as_="pre")` is invalid.** Use `rx.el.pre(...)`.
- **Long calls**: make the handler `async`, set a flag, bare `yield` to flush it to the browser, then
  `await asyncio.to_thread(...)`. Otherwise the UI freezes and the spinner never shows.
- **Menu**: built from `GROUPS`. Do not hand-write menu items.

## AXL notes

- Verify request shapes against `webui/uc_automation/schemas/cucm/current/AXLSoap.xsd` (element names, required fields, the
  result key such as `phoneButtonTemplate` vs `phoneTemplate`). Easy offline check that needs no CUCM:
  ```python
  client = zeep.Client(wsdl=(CUCM_SCHEMA_DIR/"15.0"/"AXLAPI.wsdl").as_uri(), settings=zeep.Settings(strict=False))
  svc = client.create_service('{http://www.cisco.com/AXLAPIService/}AXLAPIBinding', 'https://x:8443/axl/')
  client.create_message(svc, "addFoo", foo={...})   # raises if the shape is wrong
  ```
  Run it against an old schema (12.5) and the newest (15.0).
- Prefer AXL list/get calls over `executeSQLQuery`. SQL column names vary by release and are not
  validated by the schema.
- Features absent on older releases (for example universal device templates) must degrade to a warning,
  not an error. See `find_button_template_usage`.
- `listX` calls need `searchCriteria` with at least one element and `returnedTags`. Always pass `skip`/`first`
  through `list_paged`.

## Testing without a CUCM

1. Compile: `reflex export --frontend-only --no-zip`.
2. Request shapes: the zeep `create_message` check above.
3. Handler logic: build a state instance and call the handler function directly with fakes.
   ```python
   s = FoosState(_reflex_internal_init=True)
   FoosState._conn = lambda self: CucmConnection("x", "1.1.1.1", "u", "p")
   s.active = "x"
   FOO_SPEC.list_fn = fake_list            # patch the backend callables on the spec
   async for _ in FoosState.fetch.fn(s): pass
   ```
4. Boot: `reflex run` and confirm each route returns 200.
None of this proves the behavior on a real cluster. Say so when reporting, and try a lab CUCM.

## Conventions

- Passwords are never displayed or logged. Credentials only come from `.env/credentials.env`.
- Names and CSV column names match the AXL tags (`pattern`, `patternType`, `devicePoolName`) .
- Selection, search and counts always act on the active connection only. The web app has no multi-cluster
  mode yet.

## Known gaps

- Web logs live in `webui/logs/`. No rotation or cleanup yet.
- Login exists (see **Accounts And Access**), but there is one user store per machine and no password recovery screen. Per-page enforcement on the server is best effort (see that section). Keep the app on localhost or behind a proxy.
- Template CSVs are embedded in code (Download Template buttons); there is no examples folder.
- Phone delete does not clean up orphaned directory numbers.
- Phone button template list cannot show the base template (AXL does not return it).
- Ported: CUCM, CUC (users and call handlers), UCCX (Migrate, Script Report), CUBE (Mem Status, Config Compare), Webex and RedSky. The `Tools` platform (`/tools`, `pages/tools_home.py`) is a card page driven by `components/tools_nav.TOOLS` (Text To U-Law Audio, Make ISO Bootable, Regex Tester; the home search skips a tool already listed under another platform).

## Paste text input

Bulk Webex inputs offer a "Paste text" tab (default) beside the "CSV" tab, built with `paste_csv_tabs` (`components/tool_widgets.py`).
The text is turned into CSV bytes by `backend/paste.py` (`PastedFile`, same `read()`/`filename` as `rx.UploadFile`), so the CSV
handler logic is shared: each "from CSV" handler delegates to a `_x(files)` helper and a `x_text` event calls it through
`WebexSession._from_paste(handler, field, ...)`. The box text lives in a `paste_<field>` var set with `S.set_paste("<field>", v)`.
Delimiters: tab, pipe, semicolon, comma; the header row is optional (columns are then taken by position).
Pages with it: Add Numbers, Call Forward, Call Queues and Hunt Groups (create, replace agents), Delete Users, Add Workspace, Add Device,
Schedules (update), E911 (select locations), Check Hardware Compatibility.

Pages with a one-item input and a multiple-item input (Add Numbers, Call Forward, Reset PIN, Add Workspace, Add Device, Voicemail,
Check Hardware Compatibility, Bulk ATA/VG, Text To U-Law Audio, Set User PIN, RedSky add pages) show them as two tabs of one card,
built with `one_multiple_card` (`components/tool_widgets.py`): the single input is the first (default) tab, the bulk input the second.
Page-level explanations use `how_it_works(...)` (`components/tool_widgets.py`): a small soft "How it works" button with an info icon that opens a popover, placed right under the under-development banner. Plain info is never an inline `rx.callout`; callouts are for warnings, errors, status and "no connection" prompts.
`PanesMixin` (`state/run_mixin.py`) and `collapsible_card` remain for the Migrate pages' multiple-phones card.

### Home Cluster Locator (CUCM > Tools)

- `/cucm/home-cluster-locator`, `HomeClusterState`, `backend/cucm_home.py`. Port of the old Home Cluster Manager GUI (its "Check AXL User" is not
  included). No instance dropdown: the menu bar shows only the Org picker (`cucm_page(show_instance=False)`)
  and every saved CUCM connection of that organization is searched, replacing the old `CUCMs.csv`.
- Enter a user ID, Find User. Each cluster is asked `https://<server>:8443/cucm-uds/clusterUser?username=<id>` (UDS, no login, 5 s timeout, 10 at a time).
  The table shows Found (with the home cluster the cluster reports), Not Found or Unreachable. The summary lists the distinct home clusters
  (orange when clusters disagree). Export CSV is a browser download. Logged as "Home Cluster Locator". Not tested against a real CUCM.
- **Move**: each result row has a Home checkbox, pre-ticked on every cluster where the user was found (status Found). Several can be ticked until **Edit Home Cluster** is pressed; then only one box can be
  ticked (more than one on entry clears the selection). The panel takes an AXL username and password (backend var, used on every cluster, never saved or
  logged) and a confirm dialog guards **Update Home Cluster**. `set_home` reads `enduser.islocaluser`, runs `executeSQLUpdate` (`'t'` on the ticked
  cluster, `'f'` on every other cluster that has the user) and reads it back. The ticked cluster is done first; if it fails nothing else is changed.
  A cluster without the user is skipped (an error only for the ticked one). The search then re-runs to show the new state. Log: "Move Home Cluster".

### Text To U-Law Audio (Tools platform)

- `/tools/text-to-ulaw`, `TtsState`, `backend/tts_ulaw.py`. Port of `text-to-u-law-for-uc/tts.py`, which needed LAME and SoX installed. Now `gTTS` makes the
  MP3 (the text goes to Google Translate TTS, so internet access is required) and `av` (PyAV, bundled FFmpeg libraries, pip only) decodes, resamples and
  writes a G.711 u-law WAV, 8000 Hz, 8 bit, mono, in memory. Nothing is written to disk and nothing is installed on the machine.
- One Prompt card (file name and text) and Several Prompts (Paste Text first, then CSV, both through `_from_data`). Paste lines are `name, text` (name ends at the
  first tab, pipe or comma); CSV is `Prompt Number,Verbiage` with an optional header. File names are reduced to letters, digits, `.`, `_`, `-`. Text limit 5000 characters.
- Results use `RunMixin`. Download gives the WAV (one prompt) or a ZIP (several): browser downloads. Log: "Text To U-Law Audio" (names and sizes, never the text).

### Make ISO Bootable (Tools platform)

- `/tools/make-bootable`, `BootableState`, `backend/uc_bootable.py`. Port of `uc-make-bootable/make-bootable.py` (hdiutil mount, cp, mkisofs from cdrtools). Now
  `pycdlib` opens the ISO directly and adds an El Torito record on `isolinux/isolinux.bin` (boot catalog `isolinux/boot.cat`, load size 4, boot info table: the old
  mkisofs options) keeping the ISO's Rock Ridge and Joliet facets. Nothing is mounted or unpacked. An ISO that already has a boot record, or has no `isolinux/isolinux.bin`, is refused.
- The upload uses Reflex's streaming upload (`rx.upload_files_chunk` with a `background=True` handler taking `rx.UploadChunkIterator`), so a multi-GB ISO goes
  straight to a private temp folder (`uc-bootable-*` under the system temp dir) and is never held in memory. Needs about 2x the ISO size of free temp space.
- The result is `Bootable_<name>.iso`. It is sent by a one-time route `/bootable/<token>` (`download_app()`, a Starlette app passed to `rx.App(api_transformer=...)`;
  the token is random and unguessable), and `rx.download(url=...)` starts the browser download. The folder is deleted 60 seconds after that download finishes (so a repeated request, which React dev mode can cause, still works), after 15 minutes if it never
  starts, on any error, and at app startup (`clean_leftovers`). The upload is deleted as soon as the new ISO is written. Log: "Make ISO Bootable" (sizes, never content).
- Tested: pycdlib on synthetic ISOs (plain, Rock Ridge, Rock Ridge + Joliet), the download route and its delete, and that the page and route load. Not tested with a real Cisco ISO or a multi-GB upload, and not booted in a VM.

### Regex Tester (Tools platform)

- `/tools/regex-tester`, `RegexTesterState`, `backend/regex_tester.py`, `components/regex_ref.py`. Cards: Regex (pattern, Ignore Case, Multiline, Dot Matches Newline, Test Text),
  Match (highlighted text, alternating colors for neighbouring matches, count badge, table of position, match and groups, named groups by name), Replace (optional, `\1` or `\g<name>`)
  and the Quick Reference (Python `re` syntax; clicking a token appends it to the pattern).
- Results update as the user types (250 ms debounce). The match runs in a child `python -I` with a 3 second timeout so a catastrophic pattern cannot hang the app; limits: 500 matches, 200,000 characters of text, 5,000 of pattern.
- Python `re` flavor only (no PCRE, Java or JavaScript specifics). No operation log by design: it is a local calculation that runs on every keystroke, nothing is saved. No credentials involved.

### Home Favorites And Recently Used

- The home page (`pages/home.py`) shows two tile columns above the search box and platform cards: **Favorites** and **Recently Used** (last 10, newest first). An empty column prints "Nothing to show here."
- Both lists are route lists in browser LocalStorage (`FavoritesState`, `state/favorites.py`), so they survive reloads. Tiles come from `state/search.INDEX` (every menu item of every platform, now with an `icon`).
- Every function page (a route in `INDEX`) gets a star in the top bar (`components/layout.topbar`): grey outline, filled with the theme accent color when a favorite; clicking toggles it. The top bar's `on_mount` calls `FavoritesState.visit`, which records the page as recently used. Not clicked through in a browser.
- Settings > Home Page > **Hide Platform Cards** (`SettingsState.hide_platform_cards`, browser LocalStorage `hide_platform_cards`, per browser) hides the platform card grid on the home page. The sidebar and search are unaffected.
- Settings > **Experimental** (`SettingsState.experimental`, browser LocalStorage `experimental`, off by default) shows pages under development. Routes listed in `webex_nav.IN_DEVELOPMENT` (Naming Check, CUCM-Webex Phone Migrate) are hidden from the Webex menu, the Webex home cards and home search while it is off; with it on they show an "In Development" badge in the menu. Direct URLs still open. To mark another page, add its route to that set. The "still under development" callout (amber, `construction` icon) must be the first item on the page body, above any connection or login prompt, search box or toolbar.

## Accounts And Access

- Every page asks for a sign in. `components/layout.page()` is the one gate: until `AuthState.signed_in` it shows the sign-in screen (or the
  first-run setup screen), then the shell, and the page body only when `AuthState.can_view` (the user's access list allows the route; otherwise a "no access" notice).
  New pages need nothing extra as long as they are built with `page()` (all the `*_page` wrappers do).
- **First run:** no `webui/users.json` means no Admin yet, so the sign-in screen is replaced by "Create Admin Account" (choose a password, 8 characters or more). Admin (`admin`) always has full access, cannot be restricted, disabled or deleted, and is the only account that sees **Users** (sidebar, above Logs). Forgot the Admin password: stop the app and delete the `admin` entry in `webui/users.json`, then the setup screen returns (other users stay).
- **Users page** (`/users`): user table (Add User), and for the selected user: account enabled switch, Reset Password, Delete User, and the access tree: platform, then section, then page, each with a checkbox (a platform or section box ticks or clears everything under it, shown ticked only when all of it is). **Select All**, **Deselect All**, Expand All, Collapse All, then **Save Access**. A new user starts with no access. The tree comes from `state/search.INDEX` (every menu item) plus System > Logs, Credentials, Settings, so a new tool shows up there with no extra work. Access is stored as a list of routes, so a page added later is not granted to anyone automatically.
- **Rules** (`backend/users.can_open`): Home and the Webex login return page are open to every signed-in user; a platform home (`/cucm`) opens when any page under it is granted; `/users` is Admin only. Menu items, home cards, search results, favorite/recent tiles and the sidebar hide what the user cannot open (`components/access.py`).
- **Passwords and sessions:** scrypt hashes with a random salt in `webui/users.json` (mode 600); password inputs are uncontrolled and feed backend vars, never shown or logged. Sign in makes a random token kept in memory (`backend/users._sessions`, 12 hours idle) and in browser LocalStorage `auth_token`, so a reload keeps the user signed in; a backend restart signs everyone out. **Developer mode** (`python3 main.py --dev`, never in production): `main.py` supervises `reflex run`, restarts it when app `.py` files change, and sets `UC_DEV=1`, which makes `backend/users.py` also save sessions to `webui/.dev_sessions.json` (git-ignored, SHA-256 of each token, mode 600) so the token already in the browser stays valid after a restart. Only a real sign-in creates a session, all expiry, disable, delete and password rules still apply, and it refuses to start with a non-localhost `REFLEX_BACKEND_HOST`. 5 wrong passwords for a name in 10 minutes lock that name for 5 minutes. Changing or resetting a password, disabling or deleting a user drops that user's sessions (own password change keeps the current one).
- **Server side guard** (`state/auth_guard.AuthGuard`, registered with `app.add_middleware`): every event is checked before it runs. Reflex's own page-load plumbing and `AuthState` events pass; anything else needs a live session, and for an ordinary user the page named in the event (normalized to a registered route by Reflex; `/index` is the home page) must be one they may open. The page name comes from the browser, so this stops casual use, not a hand-made event from a signed-in user for a page they cannot open. Admin-only handlers (`UsersState`) check the Admin role themselves from the session, whatever page the event names.
- **Logs:** Sign In (success and failure, user name only), Sign Out, Set Up Admin Account, Change Own Password, Add User, Update User Access (lists the pages), Reset User Password, Delete User. No passwords.
- Not covered: the stored platform credentials are shared by everyone who can open Credentials or run a tool (access is per page, not per customer or per connection); the one-time download routes (`/bootable/<token>`, `/uccx-export/<token>`) rely on their random token and the upload endpoints were not checked against the guard. Checked: user store, guard (blocked and allowed events over the real websocket), sign in/out, restricted user views. Not checked: password reset and delete dialogs in a browser.
