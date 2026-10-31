"""Tools platform: the cards on /tools and the entries in the home search."""

# (title, route, icon, description). A tool that also sits in another platform's menu is searched under that platform only.
TOOLS: list[tuple[str, str, str, str]] = [
    ("Text To U-Law Audio", "/tools/text-to-ulaw", "audio-lines",
     "Convert text to speech and save it as a G.711 u-law WAV (8 kHz, 8 bit, mono) for UC prompts."),
]
