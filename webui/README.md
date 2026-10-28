# slab42 UC-Automations (Reflex web UI) v0.0.1

A web-native front end built with Reflex (Python backend + generated React frontend).
Unlike `../gui/`, it does not wrap the CLI scripts: features are ported into the app one at a time.

## Run

```bash
cd webui
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # once
.venv/bin/reflex run                                                  # http://localhost:3000
```

Then add a CUCM connection on the Credentials page and use the Test button.

## Developing

Architecture, how to add a new resource page, pitfalls and the testing recipe are in
[`../.doc/webui-reflex.md`](../.doc/webui-reflex.md). Read it before adding a feature.
