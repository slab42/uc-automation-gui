"""State for Tools > Make ISO Bootable: stream an uploaded Cisco UC ISO to a temp folder, add the boot record,
send the result to the browser and delete everything."""

import asyncio

import reflex as rx
from reflex_base.config import get_config

from ..backend import uc_bootable as boot
from ..backend.applog import OpLog
from ..backend.errors import UserError


class BootableState(rx.State):
    busy: bool = False
    progress: str = ""
    upload_pct: int = 0
    error: str = ""
    done_message: str = ""
    download_url: str = ""

    @rx.event
    def begin(self, selected: list[str]):
        """First step of the button click: show the upload at once (the upload itself starts in the same click)."""
        if self.busy:
            return
        if not selected:
            return rx.toast.error("Choose an ISO file first.")
        self.busy = True
        self.error = self.done_message = self.download_url = ""
        self.upload_pct = 0
        self.progress = f"Uploading {selected[0]}"

    @rx.event
    def cancel(self):
        """Stop an upload in progress (the page also stops the browser upload)."""
        self.busy = False
        self.progress = ""
        self.upload_pct = 0

    @rx.event
    def on_upload_progress(self, p: dict):
        value = float(p.get("progress", 0) or 0)
        self.upload_pct = int(value * 100) if value <= 1 else int(value)

    @rx.event(background=True)
    async def make(self, chunks: rx.UploadChunkIterator):
        log = OpLog("Make ISO Bootable", "tools-make-bootable")
        job = boot.new_job_dir()
        registered = False
        try:
            name = ""
            size = 0
            src = job / "upload.iso"
            with open(src, "wb") as f:
                async for chunk in chunks:
                    if not name:
                        name = chunk.filename
                        if not name.lower().endswith(".iso"):
                            raise boot.BootableError("Choose a .iso file.")
                    f.seek(chunk.offset)
                    f.write(chunk.data)
                    size = max(size, chunk.offset + len(chunk.data))
            if not size:
                raise boot.BootableError("No file was received.")
            log.info(f"Received {name}, {size:,} bytes")
            out_name = boot.output_name(name)
            out = job / out_name
            async with self:
                self.upload_pct = 100
                self.progress = "Upload finished. Adding the boot record and writing the new ISO"
            await asyncio.to_thread(boot.make_bootable, src, out)
            src.unlink()
            if not await asyncio.to_thread(boot.verify_bootable, out):
                raise boot.BootableError("The new ISO did not get a boot record.")
            log.info(f"Wrote {out_name}, {out.stat().st_size:,} bytes")
            token = boot.register(job, out_name)
            registered = True
            url = get_config().api_url.rstrip("/") + f"/bootable/{token}"
            async with self:
                self.download_url = url
                self.done_message = f"{out_name} is ready. The download starts now and the file is deleted a minute after it finishes."
            yield rx.download(url=rx.Var.create(url), filename=out_name)
        except UserError as e:
            log.error(str(e))
            async with self:
                self.error = str(e)
        except Exception as e:
            log.error(f"Unexpected error: {e!r}")
            async with self:
                self.error = f"Unexpected error: {e}"
        finally:
            if not registered:
                boot.remove_job_dir(job)
            async with self:
                self.busy = False
                self.progress = ""
            log.close()
