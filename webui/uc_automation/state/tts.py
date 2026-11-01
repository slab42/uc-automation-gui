"""State for Tools > Text To U-Law Audio: text to speech, converted to G.711 u-law WAV, downloaded from the browser."""

import io
import zipfile

import reflex as rx

from ..backend import tts_ulaw as tts
from ..backend.applog import OpLog
from .run_mixin import RunMixin
from .webex_routing import PasteMixin

# WAV bytes made by a running conversion, keyed by RunMixin job key. Filled from worker threads, so kept out of state.
_MADE: dict[tuple[str, str], dict[str, bytes]] = {}


class TtsState(RunMixin, PasteMixin, rx.State):
    one_name: str = ""
    one_text: str = ""
    paste_prompts: str = ""
    _files: dict[str, bytes] = {}  # file name -> WAV bytes, kept in the backend until downloaded
    file_names: list[str] = []
    _names: list[str] = []  # prompt names of the running conversion, in input order

    @rx.var
    def file_count(self) -> int:
        return len(self.file_names)

    @rx.event
    def set_one_name(self, value: str):
        self.one_name = value

    @rx.event
    def set_one_text(self, value: str):
        self.one_text = value

    @rx.event
    async def convert_one(self):
        name = tts.safe_name(self.one_name)
        if not name or not self.one_text.strip():
            yield rx.toast.error("Enter a file name and the text.")
            return
        async for ev in self._convert([(name, self.one_text.strip())], "single prompt"):
            yield ev

    @rx.event
    async def load_csv(self, files: list[rx.UploadFile]):
        if not files:
            yield rx.toast.error("Choose a CSV file first.")
            return
        async for ev in self._from_data(await files[0].read(), files[0].filename):
            yield ev
        yield rx.clear_selected_files("tts_upload")

    @rx.event
    async def load_text(self):
        if not self.paste_prompts.strip():
            yield rx.toast.error("Paste some text first.")
            return
        try:
            data = tts.paste_to_csv(self.paste_prompts)
        except tts.TtsError as e:
            yield rx.toast.error(str(e))
            return
        async for ev in self._from_data(data, "pasted text"):
            yield ev

    async def _from_data(self, data: bytes, source: str):
        """Both input tabs end here."""
        try:
            prompts = tts.parse_prompts(data)
        except tts.TtsError as e:
            yield rx.toast.error(str(e))
            return
        if not prompts:
            yield rx.toast.error("No prompts were found.")
            return
        async for ev in self._convert(prompts, source):
            yield ev

    async def _convert(self, prompts: list[tuple[str, str]], source: str):
        if self.busy:  # a second click queued behind the first would replace its job and its WAV bytes
            return
        log = OpLog("Text To U-Law Audio", "tools-text-to-ulaw")
        try:
            log.info(f"Input: {source}, {len(prompts)} prompt(s), {sum(len(t) for _n, t in prompts)} characters")
            made: dict[str, bytes] = {}

            def one(name: str, text: str):
                def run() -> str:
                    wav = tts.text_to_ulaw_wav(text)
                    made[name] = wav
                    return f"{name}.wav, {len(wav):,} bytes"
                return (name, run)

            self.file_names = []
            self._files = {}
            self._names = [n for n, _t in prompts]
            _MADE[self._job_key()] = made
            yield self._start_run([one(n, t) for n, t in prompts], "Converting", log, then="_after_convert")
        finally:
            log.close()

    def _after_convert(self, log: OpLog):
        made = _MADE.pop(self._job_key(), {})
        self._files = made
        self.file_names = [n for n in self._names if n in made]
        self._names = []

    @rx.event
    def download(self):
        if not self._files:
            return rx.toast.error("Nothing to download. Convert some text first.")
        if len(self._files) == 1:
            name, wav = next(iter(self._files.items()))
            return rx.download(data=wav, filename=f"{name}.wav")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
            for name in self.file_names:
                z.writestr(f"{name}.wav", self._files[name])
        return rx.download(data=buf.getvalue(), filename="prompts-ulaw.zip")
