"""Text to G.711 u-law WAV (8 kHz, 8 bit, mono) for UC prompts (CUCM, CUC, CUBE announcements).

Port of the old tts.py, which needed LAME and SoX on the machine. Now: gTTS speaks the text (MP3 over the internet,
the text is sent to Google Translate TTS) and PyAV (ships its own FFmpeg libraries) decodes, resamples and encodes
the u-law WAV in memory. Nothing is installed on the machine. No Reflex imports.
"""

import csv
import io
import re

from .errors import UserError

MAX_CHARS = 5000
_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_HEADERS = {"prompt number", "prompt name", "prompt", "file name", "filename", "name"}


class TtsError(UserError):
    pass


def safe_name(name: str) -> str:
    """File name without extension, limited to letters, digits, dot, dash and underscore."""
    name = name.strip()
    if name.lower().endswith(".wav"):
        name = name[:-4]
    return _NAME_RE.sub("_", name).strip("._")


def paste_to_csv(text: str) -> bytes:
    """CSV bytes from pasted `name, text` lines. The name ends at the first tab, pipe or comma, so the text may hold commas."""
    out = io.StringIO()
    w = csv.writer(out)
    for line in text.splitlines():
        if not line.strip():
            continue
        delim = next((d for d in ("\t", "|", ",") if d in line), None)
        if delim is None:
            raise TtsError(f"Line has no separator between the file name and the text: {line[:40]}")
        name, rest = line.split(delim, 1)
        w.writerow([name.strip(), rest.strip()])
    return out.getvalue().encode("utf-8")


def parse_prompts(data: bytes) -> list[tuple[str, str]]:
    """(file name, text) pairs from CSV bytes. A header row is optional; unquoted commas in the text are kept."""
    try:
        rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    except UnicodeDecodeError:
        raise TtsError("The file is not a text CSV.")
    prompts: list[tuple[str, str]] = []
    seen: set[str] = set()
    for n, row in enumerate(rows, 1):
        if not any(c.strip() for c in row):
            continue
        if n == 1 and row[0].strip().lower() in _HEADERS:
            continue
        if len(row) < 2:
            raise TtsError(f"Row {n} needs a file name and the text.")
        name, text = safe_name(row[0]), ",".join(row[1:]).strip()
        if not name or not text:
            raise TtsError(f"Row {n} needs a file name and the text.")
        if name.lower() in seen:
            raise TtsError(f"The file name {name} is used twice.")
        seen.add(name.lower())
        prompts.append((name, text))
    return prompts


def to_ulaw_wav(mp3: bytes) -> bytes:
    """Decode MP3 and return a u-law WAV, 8000 Hz, mono."""
    import av

    out = io.BytesIO()
    with av.open(io.BytesIO(mp3)) as src, av.open(out, "w", format="wav") as dst:
        stream = dst.add_stream("pcm_mulaw", rate=8000)
        stream.layout = "mono"
        resampler = av.AudioResampler(format="s16", layout="mono", rate=8000)

        def encode(frames):
            for frame in frames:
                frame.pts = None
                for packet in stream.encode(frame):
                    dst.mux(packet)

        for frame in src.decode(audio=0):
            encode(resampler.resample(frame))
        encode(resampler.resample(None))
        for packet in stream.encode(None):
            dst.mux(packet)
    return out.getvalue()


def text_to_ulaw_wav(text: str) -> bytes:
    """Speak `text` (English) and return the u-law WAV. Raises TtsError."""
    from gtts import gTTS
    from gtts.tts import gTTSError

    text = text.strip()
    if not text:
        raise TtsError("There is no text.")
    if len(text) > MAX_CHARS:
        raise TtsError(f"The text is {len(text)} characters. The limit is {MAX_CHARS}.")
    buf = io.BytesIO()
    try:
        gTTS(text=text, lang="en").write_to_fp(buf)
    except gTTSError as e:
        raise TtsError(f"Text to speech failed (internet access to Google is needed): {e}")
    except Exception as e:
        raise TtsError(f"Text to speech failed: {e}")
    try:
        return to_ulaw_wav(buf.getvalue())
    except Exception as e:
        raise TtsError(f"Audio conversion failed: {e}")
