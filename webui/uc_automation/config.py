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


PLATFORMS = [
    Platform("cucm", "CUCM", "Cisco Unified Communications Manager", "phone"),
    Platform("cuc", "CUC", "Cisco Unity Connection", "voicemail"),
    Platform("cube", "CUBE", "Cisco Unified Border Element", "router"),
    Platform("webex", "Webex", "Webex Calling / Control Hub", "message-square"),
    Platform("redsky", "RedSky", "RedSky E911 location management", "map-pin"),
    Platform("tools", "Tools", "Utilities (log search, etc.)", "wrench"),
]
