"""Regex tester: run a Python `re` pattern against a text and report the matches.

The match runs in a short-lived child interpreter with a timeout, so a catastrophic pattern (nested repeats)
cannot hang the app. Nothing is saved or logged.
"""

import json
import subprocess
import sys

TIMEOUT = 3  # seconds
MAX_MATCHES = 500
MAX_TEXT = 200_000
MAX_PATTERN = 5_000

FLAGS = {"ignorecase": "i", "multiline": "m", "dotall": "s"}

_WORKER = r"""
import json, re, sys

req = json.load(sys.stdin)
flags = 0
for name in req["flags"]:
    flags |= {"ignorecase": re.I, "multiline": re.M, "dotall": re.S}[name]
try:
    rx = re.compile(req["pattern"], flags)
except re.error as e:
    print(json.dumps({"error": f"{e.msg}" + (f" at position {e.pos}" if e.pos is not None else "")}))
    sys.exit(0)

text, limit = req["text"], req["limit"]
names = {v: k for k, v in rx.groupindex.items()}
matches = []
truncated = False
for m in rx.finditer(text):
    if len(matches) >= limit:
        truncated = True
        break
    groups = []
    for i in range(1, rx.groups + 1):
        groups.append({"label": names.get(i, str(i)), "value": m.group(i)})
    matches.append({"start": m.start(), "end": m.end(), "text": m.group(0), "groups": groups})

out = {"matches": matches, "truncated": truncated, "groups": rx.groups}
if req["replace"] is not None:
    try:
        out["replaced"] = rx.sub(req["replace"], text)
    except (re.error, IndexError) as e:
        out["replace_error"] = str(e)
print(json.dumps(out))
"""


def run(pattern: str, text: str, flags: list[str], replace: str | None = None) -> dict:
    """Return {matches, truncated, groups, replaced?, replace_error?} or {error}.
    Each match is {start, end, text, groups: [{label, value}]}."""
    if not pattern:
        return {"matches": [], "truncated": False, "groups": 0}
    if len(pattern) > MAX_PATTERN:
        return {"error": f"The pattern is longer than {MAX_PATTERN} characters."}
    if len(text) > MAX_TEXT:
        return {"error": f"The text is longer than {MAX_TEXT:,} characters."}
    request = json.dumps({"pattern": pattern, "text": text, "flags": [f for f in flags if f in FLAGS],
                          "limit": MAX_MATCHES, "replace": replace})
    try:
        done = subprocess.run([sys.executable, "-I", "-c", _WORKER], input=request, capture_output=True,
                              text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"error": f"Stopped after {TIMEOUT} seconds. The pattern is probably backtracking too much "
                         "(nested repeats such as (a+)+ are the usual cause)."}
    if done.returncode != 0:
        return {"error": "The regex check failed to run."}
    return json.loads(done.stdout)


def segments(text: str, matches: list[dict]) -> list[dict]:
    """Split the text into plain and matched pieces for the highlighted view. Matched pieces alternate
    kind 'a' and 'b' so neighbouring matches stay distinguishable. Empty matches are skipped."""
    out: list[dict] = []
    pos = 0
    n = 0
    for m in matches:
        if m["end"] == m["start"]:
            continue
        if m["start"] > pos:
            out.append({"text": text[pos:m["start"]], "kind": ""})
        out.append({"text": text[m["start"]:m["end"]], "kind": "ab"[n % 2]})
        n += 1
        pos = m["end"]
    if pos < len(text):
        out.append({"text": text[pos:], "kind": ""})
    return out
