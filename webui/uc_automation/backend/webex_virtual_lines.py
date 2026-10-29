"""Webex virtual line voicemail greetings. Ported from webex/virtualLine_voicemailGreeting.py (reference only).

The same .wav is uploaded as the busy and the unanswered greeting, and each is then set to CUSTOM (the enabled
flag and number of rings are kept). Request shapes are not tested against a real org.
"""

from .webex_api import WebexClient, WebexError
from .webex_groups import VIRTUAL_LINES

MAX_GREETING_KB = 5000
# (label, upload action, voicemail setting)
GREETINGS = (("busy", "uploadBusyGreeting", "sendBusyCalls"),
             ("unanswered", "uploadNoAnswerGreeting", "sendUnansweredCalls"))


def check_greeting(filename: str, data: bytes) -> None:
    if not filename.lower().endswith(".wav"):
        raise ValueError("The greeting must be a .wav file.")
    if len(data) > MAX_GREETING_KB * 1024:
        raise ValueError(f"The greeting is over {MAX_GREETING_KB} KB.")
    if not data:
        raise ValueError("The greeting file is empty.")


def upload_greetings(c: WebexClient, line: dict[str, str], filename: str, data: bytes, note) -> str:
    """Upload to both greetings. Raises WebexError if either step fails; `note` logs each step."""
    base = f"{VIRTUAL_LINES}/{line['id']}/voicemail"
    failed = []
    for label, action, setting in GREETINGS:
        try:
            c.call("POST", f"{base}/actions/{action}/invoke", files={"file": (filename, data, "audio/wav")})
        except WebexError as e:
            note(f"{label} greeting upload failed: {e}")
            failed.append(f"{label} upload failed ({e})")
            continue
        note(f"{label.capitalize()} greeting {filename} uploaded")
        try:
            existing = c.call("GET", base).get(setting) or {}
            section = {"enabled": existing.get("enabled", False), "greeting": "CUSTOM"}
            if setting == "sendUnansweredCalls" and "numberOfRings" in existing:
                section["numberOfRings"] = existing["numberOfRings"]
            c.call("PUT", base, body={setting: section})
            note(f"{label.capitalize()} greeting set to CUSTOM")
        except WebexError as e:
            note(f"{label} greeting set to CUSTOM failed: {e}")
            failed.append(f"{label} uploaded but not set to CUSTOM ({e}); set it in Control Hub")
    if failed:
        raise WebexError("; ".join(failed))
    return f"Busy and unanswered greetings set to {filename}"
