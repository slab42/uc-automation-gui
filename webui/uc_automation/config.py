"""Shared constants: app identity and the platform catalogue that drives the nav."""

from dataclasses import dataclass

APP_NAME = "slab42 UC-Automations"
VERSION = "0.0.1"


@dataclass(frozen=True)
class Platform:
    slug: str
    label: str
    description: str
    icon: str  # lucide icon name
    available: bool = False  # False shows a "Coming soon" badge on the home page


PLATFORMS = [
    Platform("cucm", "CUCM", "Cisco Unified Communications Manager", "phone", available=True),
    Platform("cuc", "CUC", "Cisco Unity Connection", "voicemail", available=True),
    Platform("cube", "CUBE", "Cisco Unified Border Element", "router", available=True),
    Platform("webex", "Webex", "Webex Calling / Control Hub", "message-square", available=True),
    Platform("redsky", "RedSky", "RedSky E911 location management", "map-pin", available=True),
    Platform("tools", "Tools", "Utilities (log search, etc.)", "wrench"),
]
