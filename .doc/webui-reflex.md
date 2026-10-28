# Reflex web UI (`webui/`)

The web-native replacement for `gui/`. It does not wrap the CLI scripts. Each feature is
ported into the app as Python backend code (AXL calls) plus a Reflex page. The CLI scripts in
`cucm/` are reference only and are never imported or modified. Version: `VERSION` in
`webui/uc_automation/config.py`.

Run: `cd webui && .venv/bin/reflex run` (UI on :3000, backend on :8000, localhost only).
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
backend/cucm_axl.py          shared plumbing only: AxlError, schema/version, cached zeep client, `_call`, `list_paged`, `sql_rows`
backend/cucm_routing.py      advertised patterns, partitions, calling search spaces, call pickup groups, route patterns, translation patterns
backend/cucm_hunt.py         hunt pilots, plus hunt list / line group cleanup and the line group dependency check
backend/cucm_system.py       System: audio codec preference lists, regions, locations, device pools (+ SQL dependency checks)
backend/cucm_dn.py           directory numbers: move partition, alternate numbers, orphans (SQL)
backend/cucm_tools.py        tools: EM bulk login/logout/check, phone count by device pool, set user PIN
backend/keys.py              composite row keys (pattern + partition) shared by backend and state
backend/cucm_devices.py      phones, CTI route points (delete cleans up orphaned DNs), softkey templates, common device configs, button templates, MPP workflows
backend/cucm_connections.py  saved CUCM connections ([CUCM:<name>] in .env/credentials.env)
backend/applog.py            operation logs: OpLog writer, plus list/read/export helpers for the Logs page
backend/ini_store.py         comment-preserving credentials.env editor (copied from gui/backend/ini_editor.py)
state/logs.py                LogsState: Logs page (search, read, export; no delete or import)
state/cucm.py                CucmState: connection list, active connection, credentials form, Test button
state/crud.py                CrudMixin + ResourceSpec: the shared list/search/select/add/import/export/delete logic
state/<resource>.py          one tiny class per resource: `class XState(CucmState, CrudMixin)` + a spec
components/crud_page.py      build_crud_page(): the shared page (toolbar, table, all dialogs)
components/cucm_nav.py       CUCM top menu bar. GROUPS drives the menu and the CUCM home cards
components/layout.py         sidebar, top bar, page() wrapper
pages/<resource>.py          one config per resource (columns, add form)
uc_automation.py             app + every add_page()
```

## Logging

- Every operation writes its own text file to `webui/logs/` (git-ignored): `<YYYY-MM-DD_HH-MM-SS>-<slug>.log`,
  same line format as the CLI, first line `<Title> - Started`, last line `<Title> - Completed`.
- Use `OpLog(title, slug)` from `backend/applog.py` and close it in `try/finally`. On CRUD pages call
  `self._open_log("Action")` (builds title and slug from the spec). Pass the log into `_run_each(..., log)` and
  `_fetch(log)` so a follow-up reload lands in the parent operation's log. A bare `_fetch()` opens its own "List" log.
- Covered: list/reload, add, import add/modify, delete selected, bulk delete, export, dependency check, MPP
  migrate/prep, and save/test/delete connection. New features must log too. Never log passwords.
- Logs page (`/logs`, sidebar above Credentials): newest first, search matches file names and contents,
  click a row to read it, select one or more and Export (one `.log`, or a `.zip` for several). It has no delete
  or import on purpose. The Parser mode switch replaces the file list with the last 200 log lines (oldest first)
  across all logs, filtered by the search text when there is one (`applog.parse_logs`). File names from the browser are validated against a strict pattern before any read.
- Not logged: template downloads, selection/search clicks, dialog open/close, and CSV rejections on the MPP page.

## Credentials

- Stored in `.env/credentials.env` as `[CUCM:<name>]` with `server`, `username`, `password`,
  `version` (detected CUCM release) and `schema_version` (AXL schema folder used). Same file the CLI reads.
- Passwords never reach the browser. The password input is uncontrolled and feeds a **backend var**
  (`_password`, underscore prefix = not sent to the client). Saved passwords show only as "Stored".
- The Test button calls `getCCMVersion`, derives the major release (for example 14.0), picks the
  closest installed schema (`webui/uc_automation/schemas/cucm/<version>/`, exact match else nearest older), and saves both.
- Schemas are tracked in git under `webui/uc_automation/schemas/<platform>/<version>/` (`cucm`, `cuc`); a new platform gets its own folder and a constant in `backend/paths.py`.
- The webui keeps its own copy of the schemas; it does not read the CLI's `cucm/schema/` or `cuc/schema/`.

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
copied from the CLI scripts and is the least verified part, so test it on a lab CUCM.

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
  It reuses list, search, select and the per-row results runner.

Dialogs are driven by one string var, `dialog` (`""`, `"add"`, `"import"`, `"bulk"`, `"confirm"`,
`"result"`, `"exportchoice"`, or your own name). Open with `S.set_dialog("name", True)`.

## Tool pages (not CRUD)

CUCM > Tools (`pages/tools.py`, `state/tools.py`, `components/tool_widgets.py`) are one-off runners, not lists.
`_RunMixin` gives them busy / progress / per-row results and `_run_items`, which runs each item in a thread and logs it.
Their routes are registered with `on_load=<State>.load_connections`. Secrets: PINs come from a password input (backend
var) or an uploaded CSV, go straight to CUCM or the EM servlet, and are never logged or shown. EM login and logout call
`http://<server>:8080/emapp/EMAppServlet` from the app's host, so that host must be able to reach the EM server.

## Shared behavior worth knowing

- `CrudMixin._run_each(conn, targets, op, verb, done)` runs `op(conn, target)` per target in a thread and
  records one result row each. If `op` returns a non-empty string it becomes that row's detail.
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
  (`_fetch`, `_import`, `_run_each`) that handlers forward with `async for ev in self._x(): yield ev`.
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

## Conventions carried over from the CLI

- Passwords are never displayed or logged. Credentials only come from `.env/credentials.env`.
- Names and CSV column names match the AXL tags (`pattern`, `patternType`, `devicePoolName`) so a CSV
  exported from the old scripts imports here.
- Selection, search and counts always act on the active connection only. The web app has no multi-cluster
  mode yet.

## Known gaps

- Web logs live in `webui/logs/`, not the repo-root `_logs/` the CLI uses. No rotation or cleanup yet.
- **No login.** Anyone who can reach the port can use the stored credentials. Keep it on localhost or
  behind an authenticating proxy.
- **Template CSVs are embedded in code**, not stored in `_DATA/examples/` as the CLI rule requires.
- Phone delete does not clean up orphaned directory numbers (the CLI script does).
- Phone button template list cannot show the base template (AXL does not return it).
- Only CUCM is ported. CUC, CUBE, Webex and RedSky have placeholder pages and credential tabs.
- `gui/` (old FastAPI/React wrapper) still exists and is unchanged.
