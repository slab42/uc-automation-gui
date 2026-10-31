"""Make a Cisco UC install ISO (CUCM, IMP, CUC) bootable, in pure Python.

Port of make-bootable.py, which mounted the ISO, copied it out and ran mkisofs (cdrtools) on a Mac. Cisco ships these
ISOs without an El Torito boot record even though isolinux/isolinux.bin is on them. `pycdlib` adds that boot record
(boot catalog, load size 4, boot info table: the same options the old mkisofs call used) and writes the new ISO.
Nothing is installed on the machine and the ISO is never mounted or unpacked.

Finished ISOs sit in a private temp folder, are served once by the download route (`download_app`) and deleted GRACE_SECONDS
after the download ends, or after TTL_SECONDS if it never starts. No Reflex imports.
"""

import secrets
import shutil
import tempfile
import threading
from pathlib import Path

from .errors import UserError

TTL_SECONDS = 900  # delete if the download never starts
GRACE_SECONDS = 60  # delete this long after a download finishes (a repeated request, e.g. React dev mode, still works)
_PREFIX = "uc-bootable-"
_lock = threading.Lock()
_jobs: dict[str, tuple[Path, str]] = {}  # token -> (job folder, file name)


class BootableError(UserError):
    pass


def new_job_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix=_PREFIX))


def remove_job_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def clean_leftovers() -> None:
    """Remove job folders a crashed earlier run left behind (call once at startup)."""
    for p in Path(tempfile.gettempdir()).glob(_PREFIX + "*"):
        shutil.rmtree(p, ignore_errors=True)


def output_name(upload_name: str) -> str:
    name = Path(upload_name or "uc.iso").name
    return name if name.lower().startswith("bootable_") else f"Bootable_{name}"


def make_bootable(src: Path, dst: Path) -> None:
    """Write `dst`, a copy of the ISO `src` with an El Torito boot record on isolinux/isolinux.bin."""
    import pycdlib
    from pycdlib.pycdlibexception import PyCdlibException

    iso = pycdlib.PyCdlib()
    try:
        iso.open(str(src))
    except PyCdlibException as e:
        raise BootableError(f"This is not a readable ISO 9660 image: {e}")
    try:
        if iso.eltorito_boot_catalog is not None:
            raise BootableError("This ISO is already bootable.")
        rr, joliet = iso.has_rock_ridge(), iso.has_joliet()
        boot = None
        try:
            if rr:
                boot = iso.full_path_from_dirrecord(iso.get_record(rr_path="/isolinux/isolinux.bin"))
            else:
                boot = "/ISOLINUX/ISOLINUX.BIN;1"
                iso.get_record(iso_path=boot)
        except PyCdlibException:
            boot = None
        if boot is None:
            raise BootableError("isolinux/isolinux.bin was not found. This does not look like a Cisco UC install ISO.")
        try:
            iso.add_eltorito(
                boot, "/ISOLINUX/BOOT.CAT;1",
                rr_bootcatname="boot.cat" if rr else None,
                joliet_bootcatfile="/isolinux/boot.cat" if joliet else None,
                boot_load_size=4, boot_info_table=True,
            )
            iso.write(str(dst))
        except PyCdlibException as e:
            raise BootableError(f"Could not add the boot record: {e}")
    finally:
        iso.close()


def verify_bootable(path: Path) -> bool:
    import pycdlib

    iso = pycdlib.PyCdlib()
    iso.open(str(path))
    try:
        return iso.eltorito_boot_catalog is not None
    finally:
        iso.close()


# --- one-time download ---

def register(job_dir: Path, filename: str) -> str:
    """Offer the single file in `job_dir` for one download. Returns the token for /bootable/<token>."""
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
    """Forget the token and delete its job folder."""
    with _lock:
        entry = _jobs.pop(token, None)
    if entry:
        remove_job_dir(entry[0])


def download_app():
    """Starlette app with the one-time download route. Mounted in front of the Reflex backend (api_transformer)."""
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
        return FileResponse(path, media_type="application/x-iso9660-image", filename=filename,
                            background=BackgroundTask(_later, token, GRACE_SECONDS))

    return Starlette(routes=[Route("/bootable/{token}", get, methods=["GET"])])
