# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

uc-automation is a collection of Python scripts for Unified Communications automation across on-premise (CUCM), (CUC) and cloud (Webex) platforms. There are also scripts for CUBE management and maintenance.  CUCM and CUC scripts use Cisco's AXL SOAP API via zeep; Webex scripts use REST APIs; CUBE scripts can use SSH or the APIs.

## Hard Rules
- ** Password visibility ** Anytime a script prompts for a password, it should never be displayed on screen.
- Paswords should always be stored or requested from the .env/credentials.env file.
- All CSV input files should be created in the _DATA folder.  Also examples of these files should be included in the _DATA/examples folder.
- Script comments should always be at the very top of the script
- Customer variable files (.var files) are not checked in; each customer maintains their own .var file matching the .var.EXAMPLE
- Every script must carry a `# TITLE: <short name>` line (max 40 chars, Title Case) within its first 5 lines - directly after the shebang, or as line 1 when there is no shebang. `main.py` uses it as the menu label, and a script without one will not appear in the launcher at all.
- The module docstring is the first statement after the TITLE line. Nothing (not even `import warnings`) goes above it.
- Logs always go to the repo-root `_logs/` folder: `log_file = f"../_logs/{timestamp}-<script-name>.log"`. Create the logger before any cluster selection or credential prompt, log `"<Title> - Started"` and `"<Title> - Completed"`, and pass `logger` into functions rather than relying on a module-global.
- Cluster and router selection always goes through `setup/multi_object_loader.py` (single or multi object flow). Scripts never carry their own CSV reader or credential menu.

## Directory Structure

- **cucm/** - Cisco Unified Communications Manager automation scripts
  - Individual operation scripts (add/remove/move patterns, update phone loads, etc.)
  - `general.py` - Shared utilities for HTTP setup (legacy, use multi_object_loader for new scripts)
  - `ucmAPI.py` - AXL SOAP client wrapper class around zeep
  - `schema/<version>/` - WSDL files required for AXL (one per CUCM version)

- **webex/** - Webex/Calling automation scripts
  - Individual operation scripts for locations, users, call queues, etc.
  - Typically use `general.py` from cucm/

  - `GET /telephony/config/locations` (Calling admin API, `spark-admin:telephony_config_read`) and `GET /v1/locations` (core/base Locations API, `spark-admin:locations_read`) are **different API families with different scopes** — this app's integration has the former, not the latter. Don't confuse them when debugging location-related 403s.

- **cuc/** - Cisco Unity automation scripts
  - Individual operation scripts (mailbox checks, call handler export/delete, call tree workbook)
  - `cucAPI.py` - REST (vmrest) client wrapper class, counterpart of `cucm/ucmAPI.py`; all CUC scripts use it
  - `schema/<version>/` - REST schema artifacts; use application.wadl file for schema first
  - Same cluster/credential flow as CUCM: select from `_DATA/clusters.csv` (`cluster_type=cuc` rows), single or multi cluster, credentials from `[CUC:<name>]` / `[CUC:default]`

- **cube/** - Cisco CUBE scripts
  - Individual operation scripts (memory status check, config template comparison) over SSH via netmiko
  - Same router/credential flow: select from `_DATA/routers.csv`, single or multi router, credentials from `[CUBE:<hostname>]` / `[CUBE:default]`
  - HTML reports are written to `_DATA/reports/`

- **gui/** - Web front end (`python3 main.py --gui`)
  - `backend/` - FastAPI app, PTY script runner, credentials.env editor
  - `frontend/` - React (Vite + TypeScript) app; `dist/` is the build output and is not checked in

- **setup/** - Shared utilities and loaders
  - `multi_object_loader.py` - loads clusters/routers from CSV and manages credential prompting
  - `env_loader.py` - loads configuration and credentials from .env files
  - `logger.py` - centralized logging setup
  - `var_loader.py` - loads customer-specific variables from .var files

- **_DATA/** - Configuration data
  - `clusters.csv` - cluster definitions for CUCM and CUC scripts
  - `routers.csv` - router definitions for CUBE scripts

- **.env/** - Environment configuration (not checked in)
  - `credentials.env` - credentials for all clusters and routers
  - `customer_env.json` - customer-specific configuration

- **.var/** - Customer environment variables for scripts.
  - `.var/examples/` folder includes example `.var.EXAMPLE` files for all scripts with customer variables
  - All scripts requiring customer-specific variables must have an associated `<script-name>.var.EXAMPLE` file
  - Each script is matched to its runtime `.var` file (e.g., `check_router_mem_status.py` → `check_router_mem_status.var`)
  - `.var` files are not checked in; each customer maintains their own configuration

## Dependencies

Install via pip:
```bash
pip install zeep requests lxml urllib3
```

Key dependencies:
- `zeep` - SOAP/WSDL client for Cisco AXL API
- `requests` - HTTP library with retry logic
- `lxml` - XML parsing
- `urllib3` - HTTP with connection pooling

Optional, needed only by specific scripts (each script prints an install hint if missing):
- `netmiko` - SSH to routers (`cube/` scripts)
- `openpyxl` - Excel output (`cuc/build_call_trees.py`)

Python 3.6+ required (f-strings used throughout).

## Cluster and Router Configuration

All scripts use CSV files for cluster/router definitions:
- **clusters.csv** - used by CUCM and CUC scripts (columns: cluster_name, server, version)
- **routers.csv** - used by CUBE scripts (columns: router_ip, hostname)

Files located at: `_DATA/clusters.csv` and `_DATA/routers.csv`

Example clusters.csv:
```csv
cluster_name,server,version
CUCM1,192.168.1.100,15.0
CUCM2,192.168.1.101,14.0
```

Example routers.csv:
```csv
router_ip,hostname
10.0.0.1,cube-sfo
10.0.0.2,cube-nyc
```

## Credentials Configuration

Credentials stored in `.env/credentials.env` (INI format):

```ini
[CUCM:default]
username = axl_user
password = 

[CUCM:CUCM1]
username = cucm1_user
password = 

[CUC:default]
username = cuc_admin
password = 

[CUBE:cube-sfo]
username = cube_user
password = 
```

Password can be blank to prompt at runtime (recommended for security). Credentials hierarchy:
1. Try object-specific credentials (e.g., CUCM:CUCM1, CUBE:cube-sfo)
2. Fall back to default credentials (e.g., CUCM:default, CUC:default)
3. Prompt user if neither found

For multi-object operations, script asks: "Use same credentials for all objects?" 
- Yes: loads default or single credential set
- No: prompts per-object

## Customer Variables Configuration

Scripts that require customer-specific variables (e.g., thresholds, timeouts, API endpoints) use the `var_loader.py` module. Workflow:

1. Script needs customer variables: add a "Customer Variables" section at the top (before imports) in docstring
2. Define variables in `<script-name>.var.EXAMPLE` in `.var/examples/` folder
3. Script calls `load_customer_variables(script_name)` from `var_loader.py`
4. If `.var` file exists:
   - Display loaded variables
   - Ask user to validate they are correct
   - Load and return as dict
5. If `.var` file does not exist:
   - Display path to `.var.EXAMPLE`
   - Ask user to create it based on the example
   - On creation, ask: "Enter values interactively?" 
     - Yes: prompt for each variable and save to `.var`
     - No: open file for manual editing and end script; show path to `.var`
6. Return variables dict to script for use

Example `.var.EXAMPLE`:
```ini
[variables]
memory_threshold = 80
timeout_seconds = 30
api_endpoint = https://example.com/api
```

## Running Scripts

`python3 main.py` is the single entry point for every script in this repo. It presents an interactive menu grouped by category (CUCM, CUC, CUBE, Webex) and runs the chosen script as a subprocess. Use `python3 main.py --list` to see the full inventory (path, title, flags) without launching the menu. See `.doc/main-py-launcher.md` for the launcher's design.

`python3 main.py --gui` serves the same inventory as a web app ("slab42 UC-Automations") at http://127.0.0.1:8420/: FastAPI backend in `gui/backend/`, React frontend in `gui/frontend/` (build once with `cd gui/frontend && npm install && npm run build`). Scripts run unchanged: a `sitecustomize` shim in `gui/backend/shim/` turns every `input()`/`getpass()` prompt into a web form field (no terminal in the browser), argparse flags become an options form, and the Settings page edits `.env/credentials.env` without ever displaying a password. Keep new scripts to the existing prompt conventions (`prompt_yes_no`, numbered `Select ... [1-N]:` lists, `[default]` suffixes) so the GUI can classify them. Design notes: `.doc/gui-web-frontend.md`. Update that doc in the same commit as any GUI change.

## Reflex Web UI (`webui/`) - the going-forward GUI

`webui/` is the new web app (Reflex, Python backend). It is NOT a wrapper around the CLI scripts: every
feature is re-implemented as backend AXL code + a Reflex page, and the CLI scripts are reference only
(never import or modify them). `gui/` is the old wrapper and is frozen. Run: `cd webui && .venv/bin/reflex run`.

Full guide: `.doc/webui-reflex.md`. Read it before touching `webui/`, and update it in the same commit as any
structural change. The rules:
- Three layers: `backend/` (plain Python AXL, no Reflex), `state/` (Reflex state), `pages/` + `components/` (layout only).
- A new CUCM list/add/modify/delete resource is: backend functions + a `ResourceSpec` + `class XState(CucmState, CrudMixin)`
  + a `build_crud_page(...)` config + one `add_page` + one entry in `GROUPS` (`components/cucm_nav.py`). Do not copy the page code.
- Custom behavior goes through `CrudPageConfig.extra_toolbar` / `extra_dialogs`, not a forked page.
- Menu, sub-menu, tab and segmented-control labels use Title Case: every word starts with a capital letter, including small words
  ("Phone Count By DP", "Paste Text", "Non-Subscriber With Menu Entries"). Acronyms stay upper case.
- Passwords stay in backend (`_`-prefixed) vars and `.env/credentials.env`; never send one to the browser.
- Check AXL request shapes against `cucm/schema/current/AXLSoap.xsd` with zeep `create_message`, and compile with
  `reflex export --frontend-only --no-zip`. Say plainly that nothing was tested against a real CUCM.

## Running CUCM/CUC/CUBE Scripts

All scripts follow the same pattern:

1. Run script: `python3 script_name.py`
2. Interactive prompts:
   - Select cluster (CUCM/CUC) or router (CUBE) from CSV
   - Load or prompt for credentials
   - Single item or CSV mode for operations
   - For CSV mode, path to operation CSV file
3. Logs written to `_logs/<timestamp>-<script_name>.log`

Example:
```bash
python3 cucm/move_DN_partition.py
# Prompts to select CUCM cluster from clusters.csv
# Prompts for credentials (checks CUCM:default first)
# Prompts for single or CSV mode
# Processes DNs from mv_dnPartitions.csv
# Logs to _logs/2025-XX-XX_HH-MM-SS-move_DN_partition.log
```

## CUCM Script Conventions

Each script docstring specifies its CSV format (field order matters):

- `add_advertisted_pattern.py` - adds Advertised Patterns (Hosted DN/PSTN routes)
- `remove_advertisted_pattern.py` - removes patterns; auto-retries with `+` prefix if needed
- `remove_DN_EnterpriseAlternateNumber.py` - clears alternate number settings on a DN
- `move_DN_partition.py` - moves DN to a different Route Partition
- `update_LoadServer.py` - updates phone load parameters
- `update_PhoneLoad.py` - updates phone firmware load

## Core Modules

### general.py

Provides shared utilities imported by all scripts:

- `serverSetup(configPath, logPath)` - reads JSON config file, returns server dict with keys: `server`, `username`, `password`, `version`
- `loggerSetup(logPath)` - creates dual-output logger (stdout + rotating file)
- `httpSetup()` - returns requests.Session with retry logic (for non-SOAP HTTP calls in webex scripts)
- `findFiles(searchPath, searchPattern)` - glob wrapper, returns sorted list

### ucmAPI.py

`AXL` class wraps zeep SOAP client:

- `__init__(username, password, wsdl, cucm, cucm_version)` - connects to CUCM, builds zeep client from WSDL
- Methods for each operation: `add_advertised_patterns()`, `remove_advertised_patterns()`, `add_line()`, `update_device()`, etc.
- All methods return dict: `{'success': bool, 'response': str, 'error': str}`
- SSL verification disabled (ignores urllib3 warnings)

## WSDL Schema Files

CUCM scripts require matching WSDL for the target UCM version. Store in `cucm/schema/<version>/AXLAPI.wsdl`.

Scripts load WSDL based on cluster version from clusters.csv: `cucm/schema/{version}/AXLAPI.wsdl`

If running against a new CUCM version:
1. Download AXLAPI.wsdl from CUCM server or Cisco documentation
2. Place in `cucm/schema/<new_version>/`
3. Update `_DATA/clusters.csv` with the new version

## CSV Operation Files

Operation CSV files contain the data to process (e.g., DNs to move, patterns to add). Field order matters; headers are skipped. Scripts ignore extra fields to allow flexible templates.

Examples:
- `mv_dnPartitions.csv` - DNs to move (columns: dn, partition)
- `advertisedPatterns.csv` - patterns to add (columns: description, pattern, patternType, etc.)

## Script Loading and Credential Flow

**Single-Object Scripts (most CUCM/CUC/CUBE scripts):**
1. Import from `multi_object_loader`: `get_object_for_single_operation()`, `load_credentials()`
2. Load cluster/router: select from CSV or provide manually
3. Load credentials: check stored (object-specific, then default), prompt if missing
4. Initialize AXL/API client
5. Prompt for single item or CSV mode
6. Execute operations, log results

**Multi-Object Scripts (future bulk scripts):**
1. Import from `multi_object_loader`: `get_objects_for_multi_operation()`, `load_credentials_for_multi_objects()`
2. Load all clusters/routers from CSV
3. Ask: "Use same credentials for all objects?"
4. Load credentials (once for all, or per-object)
5. Execute operations on each object, log results

**Error Handling:**
- AXL API errors caught as zeep.exceptions.Fault; logged with error message
- CSV parsing is lenient: searches for column headers and ignores extra fields
- Network retries handled by httpSetup() session

**Logging:**
- All scripts use dual-output logging (stdout + file)
- File logs in `_logs/` with timestamp and script name
- Log level: DEBUG (all operations logged)

## Common Development Tasks

**Adding a new CUCM/CUC/CUBE script:**
1. Import from `multi_object_loader`: `get_object_for_single_operation()`, `load_credentials()`
2. Import from `setup.logger`: `setup_logger()`
3. Load cluster/router and credentials (see Script Loading section above)
4. Initialize AXL (CUCM/CUC) or API client (CUBE)
5. Prompt for single vs. CSV mode
6. Process data, call API, log results
7. Document operation CSV format in docstring
8. Add a `# TITLE: <short name>` line in the first 5 lines so the script appears in the `main.py` launcher menu. See `.doc/main-py-launcher.md` for launcher design; update that doc in the same commit as any launcher change.

**Adding customer variables to a script:**
1. Create `.var.EXAMPLE` file in `.var/examples/` (INI format with `[variables]` section)
2. Document variable requirements in script docstring, add "Customer Variables:" section (after opening description, before other sections)
3. Import `load_customer_variables()` from `var_loader.py` in setup/
4. Call early in main() (after logger setup): `vars = load_customer_variables(__file__, logger)`
5. Add comment: `# Load customer variables from .var file`
6. Use variables throughout script from returned dict: `vars['variable_name']`
7. Provide sensible defaults when unpacking variables in case user skips var_loader workflow

**Extending ucmAPI.py:**
1. Add method to AXL class
2. Name as `verb_noun()` (e.g., `add_line()`, `remove_device()`)
3. Return standard dict: `{'success': bool, 'response': str, 'error': str}`
4. Catch zeep.exceptions.Fault and populate error field

**Debugging API calls:**
- Check `_logs/` directory for detailed operation trace
- CUCM/CUC server logs available on admin GUI
- Zeep's HistoryPlugin attached to AXL client (rarely needed)
