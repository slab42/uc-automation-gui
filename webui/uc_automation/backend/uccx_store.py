"""The one stored UCCX download, kept in `webui/uccx_download/` for a short time.

Layout (same as the old uccxTools `backup/` folder): `xml/` admin settings, `finesse/` Finesse settings, `scripts/` and
`prompts/` the uploaded files, plus `download.json` (where it came from and when). A new download replaces the old
one. The folder is removed by Delete, by `prune` once it is older than MAX_AGE_DAYS (run at app start) or by hand.

A zip export is built in a private temp folder, served once by the download route (`download_app`) and deleted
GRACE_SECONDS after the download ends, or after TTL_SECONDS if it never starts. No Reflex imports.
"""

import json
import secrets
import shutil
import tempfile
import threading
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from .paths import UCCX_DOWNLOAD_DIR as DIR
from .uccx_api import local_name

MAX_AGE_DAYS = 7
TTL_SECONDS = 900  # delete the zip if the download never starts
GRACE_SECONDS = 60  # delete this long after a download finishes (a repeated request, e.g. React dev mode, still works)
SUBDIRS = ("xml", "finesse", "scripts", "prompts")
_INFO = DIR / "download.json"
_PREFIX = "uc-uccx-export-"
_lock = threading.Lock()
_jobs: dict[str, tuple[Path, str]] = {}  # token -> (job folder, file name)


def _read_info() -> dict:
    try:
        return json.loads(_INFO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_info(info: dict) -> None:
    _INFO.write_text(json.dumps(info, indent=2), encoding="utf-8")


def _walk(sub: str):
    return [p for p in (DIR / sub).rglob("*") if p.is_file()] if (DIR / sub).is_dir() else []


def current() -> dict[str, str] | None:
    """What is stored, for the page (strings only), or None when nothing is."""
    if not DIR.is_dir() or not any(DIR.iterdir()):
        return None
    info = _read_info()
    files = [p for p in DIR.rglob("*") if p.is_file() and p != _INFO]
    mb = sum(p.stat().st_size for p in files) / (1024 * 1024)
    created = info.get("created", "")
    return {
        "source": info.get("source", "Unknown"),
        "server": info.get("server", ""),
        "created": created.replace("T", " ")[:16],
        "complete": "yes" if info.get("complete") else "no",
        "size": f"{mb:.1f} MB",
        "xml": str(len(_walk("xml"))),
        "finesse": str(len(_walk("finesse"))),
        "scripts": str(len([p for p in _walk("scripts") if p.suffix.lower() == ".aef"])),
        "prompts": str(len([p for p in _walk("prompts") if p.suffix.lower() == ".wav"])),
    }


def exists() -> bool:
    return current() is not None


def start(source: str, server: str) -> Path:
    """Empty the store and lay out the folders for a new download."""
    delete()
    DIR.mkdir(parents=True, exist_ok=True)
    for sub in SUBDIRS:
        (DIR / sub).mkdir(exist_ok=True)
    _write_info({"source": source, "server": server, "created": datetime.now().isoformat(timespec="seconds"),
                 "complete": False})
    return DIR


def finish(areas: list[dict[str, str]]) -> None:
    info = _read_info()
    info["complete"] = all(a["status"] == "OK" for a in areas)
    info["areas"] = areas
    _write_info(info)


def delete() -> None:
    shutil.rmtree(DIR, ignore_errors=True)


def prune() -> None:
    """Delete the stored download once it is older than MAX_AGE_DAYS (call at startup)."""
    if not DIR.is_dir():
        return
    try:
        created = datetime.fromisoformat(_read_info().get("created", ""))
    except ValueError:
        created = datetime.fromtimestamp(DIR.stat().st_mtime)
    if datetime.now() - created > timedelta(days=MAX_AGE_DAYS):
        delete()


def script_files() -> list[str]:
    """Stored scripts (.aef) as paths relative to the scripts folder, sorted."""
    base = DIR / "scripts"
    return sorted(p.relative_to(base).as_posix() for p in _walk("scripts") if p.suffix.lower() == ".aef")


def read_script(rel: str) -> bytes:
    """One stored script. `rel` must be one of script_files() (never a path from the browser as is)."""
    if rel not in script_files():
        raise FileNotFoundError(rel)
    return (DIR / "scripts" / rel).read_bytes()


# --- zip export, served once ---

def new_export_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix=_PREFIX))


def remove_export_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def clean_leftovers() -> None:
    """Remove export folders a crashed earlier run left behind (call once at startup)."""
    for p in Path(tempfile.gettempdir()).glob(_PREFIX + "*"):
        shutil.rmtree(p, ignore_errors=True)


def export_zip(job_dir: Path) -> str:
    """Write the stored download as a zip inside `job_dir` and return its file name."""
    info = current()
    if info is None:
        raise FileNotFoundError("No stored download.")
    stamp = datetime.now().strftime("%Y_%m_%d-%H_%M_%S")
    root = f"uccx-{local_name(info['server'] or info['source'])}-{stamp}"
    name = f"{root}.zip"
    with zipfile.ZipFile(job_dir / name, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(DIR.rglob("*")):
            if p.is_file():
                z.write(p, f"{root}/{p.relative_to(DIR).as_posix()}")
    return name


def register(job_dir: Path, filename: str) -> str:
    """Offer the single file in `job_dir` for one download. Returns the token for /uccx-export/<token>."""
    token = secrets.token_urlsafe(32)
    with _lock:
        _jobs[token] = (job_dir, filename)
    _later(token, TTL_SECONDS)
    return token


def _later(token: str, seconds: float) -> None:
    timer = threading.Timer(seconds, discard, args=(token,))
    timer.daemon = True
    timer.start()


def discard(token: str) -> None:
    """Forget the token and delete its export folder."""
    with _lock:
        entry = _jobs.pop(token, None)
    if entry:
        remove_export_dir(entry[0])


def download_app():
    """Starlette app with the one-time zip route. Mounted in front of the Reflex backend (api_transformer)."""
    from starlette.applications import Starlette
    from starlette.background import BackgroundTask
    from starlette.exceptions import HTTPException
    from starlette.responses import FileResponse
    from starlette.routing import Route

    async def get(request):
        token = request.path_params["token"]
        with _lock:
            entry = _jobs.get(token)
        if entry is None:
            raise HTTPException(404, "This download is no longer available.")
        job_dir, filename = entry
        path = job_dir / filename
        if not path.is_file():
            discard(token)
            raise HTTPException(404, "This download is no longer available.")
        return FileResponse(path, media_type="application/zip", filename=filename,
                            background=BackgroundTask(_later, token, GRACE_SECONDS))

    return Starlette(routes=[Route("/uccx-export/{token}", get, methods=["GET"])])
