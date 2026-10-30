# slab42 UC-Automations (Reflex web UI) v0.0.1

Web app built with Reflex (Python backend + generated React frontend) for CUCM, CUC, CUBE, Webex and RedSky automation.

## Run

From the repo root:

```bash
python3 main.py            # creates webui/.venv on first run, then serves http://localhost:3000
python3 main.py --setup    # only create or refresh webui/.venv
```

Or by hand:

```bash
cd webui
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # once
.venv/bin/reflex run
```

Then add connections on the Credentials page. They are saved to `.env/credentials.env` at the repo root
(template: `credentials.env.EXAMPLE`).

## Layout

- `uc_automation/` the app (backend, state, pages, components, schemas)
- `credentials.env.EXAMPLE` template for `.env/credentials.env`

## Developing

Architecture, how to add a new resource page, pitfalls and the testing recipe are in
[`../.doc/webui-reflex.md`](../.doc/webui-reflex.md). Read it before adding a feature.
