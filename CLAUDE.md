# CLAUDE.md

Guidance for Claude Code (claude.ai/code) in this repository.

## Project Overview

slab42 UC-Automations is a Reflex web app (Python backend, generated React frontend) for Unified Communications
automation: CUCM and CUC (Cisco AXL SOAP via zeep, CUC REST), CUBE routers (SSH via netmiko), Webex Calling (REST) and
RedSky E911 (REST). There is no CLI. The old CLI scripts and the `gui/` wrapper were removed; see git history.

Run it with `python3 main.py` from the repo root. It creates `webui/.venv` on first run, installs
`webui/requirements.txt` and starts `reflex run` (UI http://localhost:3000, backend :8000, localhost only).
`python3 main.py --setup` only creates or refreshes the venv.

## Repository Layout

- `main.py` - launcher for the web app (nothing else)
- `webui/` - the app
  - `uc_automation/` - `backend/` (plain Python API code), `state/` (Reflex state), `pages/` and `components/` (layout), `schemas/` (AXL/CUC schemas, one folder per platform and version), `uc_automation.py` (app and routes)
  - `reference/` - API references (tracked, not ignored): `webex-cloud-calling.json`, `webex-contact-center.json`, `webex-device.json`, `redsky-api-docs.json`. Use them when adding Webex or RedSky functionality.
  - `requirements.txt` - the only requirements file, `.venv/` is the only virtual environment
  - `credentials.env.EXAMPLE` - template for `.env/credentials.env`
  - `logs/` - one log file per operation (git-ignored)
- `.env/credentials.env` - credentials for every platform (git-ignored). The Credentials page edits it.
- `.doc/webui-reflex.md` - the architecture and feature guide. **Read it before touching `webui/`** and update it in the same commit as any structural or feature change.
- `uc-automation-gui.code-workspace` - the user's editor workspace (git-ignored, leave it alone)

## Hard Rules

- **Passwords never reach the browser and are never logged.** Keep them in backend (`_`-prefixed) state vars and in `.env/credentials.env`. The UI only shows "Stored".
- Manual credential entry (CUBE "Enter Manually") is never saved.
- Three layers: `backend/` (no Reflex imports), `state/` (calls the backend in a thread), `pages/` + `components/` (layout only).
- Menu, sub-menu, tab and segmented-control labels use Title Case: every word starts with a capital letter, including small words ("Phone Count By DP", "Paste Text"). Acronyms stay upper case.
- Any bulk input that accepts a CSV must offer "Paste Text" as the first (default) tab and CSV second, both routed through the same handler (`paste_csv_tabs` + `PasteMixin`, or `list_input_parts`).
- Every operation writes a log with `OpLog` (`backend/applog.py`): first line `<Title> - Started`, last line `<Title> - Completed`, closed in `try/finally`. New features must log too.
- Exports (CSV, HTML reports) are browser downloads, not files on disk.

## Adding Things

- A new CUCM list/add/modify/delete resource is: backend functions + a `ResourceSpec` + `class XState(CucmState, CrudMixin)` + a `build_crud_page(...)` config + one `add_page` + one entry in `GROUPS` (`components/cucm_nav.py`). Do not copy the page code. Custom behavior goes through `CrudPageConfig.extra_toolbar` / `extra_dialogs`.
- A new platform tool follows its platform's nav (`components/<platform>_nav.py` `GROUPS` drives the menu, home cards and home search), a page in `pages/`, a state in `state/` and an `add_page` in `uc_automation.py`.
- Credentials per platform live in `[<SERVICE>:<name>]` sections of `.env/credentials.env` (`CUCM`, `CUC`, `CUBE`, `WEBEX`, `REDSKY`) through `backend/ini_store.py`.
- Check AXL request shapes against `webui/uc_automation/schemas/cucm/<version>/AXLSoap.xsd` with zeep `create_message`.

## Verifying Changes

- Compile check (fails on any bad page): `cd webui && .venv/bin/reflex export --frontend-only --no-zip`
- Boot check: `python3 main.py` and confirm the routes return 200. Do not `pkill -f "reflex run"`: the user may have their own instance running on :3000. Stop only the PID you started.
- Say plainly that nothing was tested against a real CUCM, CUC, router, Webex org or RedSky tenant unless it was. Parsers and request builders can be run on sample data.

## Dependencies

`webui/requirements.txt`: `reflex`, `zeep`, `requests`, `lxml`, `urllib3`, `openpyxl` (CUC call tree workbook), `netmiko` (CUBE SSH). Python 3.10 or newer.
