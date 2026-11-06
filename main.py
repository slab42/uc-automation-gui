#!/usr/bin/env python3
"""Launch the slab42 UC-Automations web UI (Reflex, webui/).

Usage:
    python3 main.py             start the app (UI on http://localhost:3000, backend on :8000)
    python3 main.py --setup     create or refresh webui/.venv from webui/requirements.txt, then start the app
    python3 main.py --update    install new requirements and upgrade existing ones in webui/.venv, then start the app
    python3 main.py --dev       DEVELOPER ONLY: restart the app when Python files change and keep browser sign-ins
                                across restarts (never use on a shared or production host)

The first run creates webui/.venv and installs the requirements. Credentials live in
.env/credentials.env (see webui/credentials.env.EXAMPLE); the Credentials page edits that file.
"""

from __future__ import annotations

import glob
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

WEBUI = Path(__file__).resolve().parent / "webui"
VENV = WEBUI / ".venv"
REQUIREMENTS = WEBUI / "requirements.txt"
BIN = VENV / ("Scripts" if os.name == "nt" else "bin")
EXE = ".exe" if os.name == "nt" else ""
REFLEX = BIN / f"reflex{EXE}"
PYTHON = BIN / f"python{EXE}"
# gTTS pins click<8.2 (only its unused CLI needs it) while reflex needs click>=8.2, so it is installed without deps.
# Its other dependency, requests, is already in requirements.txt.
GTTS = "gTTS==2.5.4"


def find_python() -> str | None:
    """A Python 3.10+ interpreter: the one running this script, else the newest one on PATH."""
    if sys.version_info >= (3, 10):
        return sys.executable
    for minor in (14, 13, 12, 11, 10):
        found = shutil.which(f"python3.{minor}")
        if found:
            return found
    # pyenv and Homebrew installs that are not first on PATH
    home = os.path.expanduser("~")
    for pattern in (f"{home}/.pyenv/versions/3.*/bin/python3", "/opt/homebrew/bin/python3.1[0-9]",
                    "/usr/local/bin/python3.1[0-9]"):
        for path in sorted(glob.glob(pattern), reverse=True):
            probe = subprocess.run([path, "-c", "import sys;print(sys.version_info>=(3,10))"],
                                   capture_output=True, text=True)
            if probe.stdout.strip() == "True":
                return path
    return None


def setup(upgrade: bool = False) -> int:
    """Create webui/.venv if needed and install the requirements into it (upgrading them if asked)."""
    if not PYTHON.exists():
        python = find_python()
        if python is None:
            print("Python 3.10 or newer is required (python3.10 ... python3.14 on PATH).")
            return 1
        print(f"Creating {VENV} with {python} ...")
        subprocess.run([python, "-m", "venv", str(VENV)], check=True)
    print("Updating requirements ..." if upgrade else "Installing requirements ...")
    cmd = [str(PYTHON), "-m", "pip", "install", "-q", *(["--upgrade"] if upgrade else []), "-r", str(REQUIREMENTS)]
    subprocess.run(cmd, check=True)
    subprocess.run([str(PYTHON), "-m", "pip", "install", "-q", "--no-deps", GTTS], check=True)
    return 0


def run_dev(extra: list[str]) -> int:
    """Developer mode: run reflex as a child, restart it when the app's Python files change or it exits.

    Sets UC_DEV=1 so backend/users.py keeps sessions in webui/.dev_sessions.json (hashed tokens), which makes the
    token already in the browser valid after a restart. Only the child this script started is ever stopped.
    """
    from watchfiles import watch  # a dependency of reflex, installed in the venv

    host = os.environ.get("REFLEX_BACKEND_HOST", "")
    if host and host not in ("localhost", "127.0.0.1", "::1"):
        print(f"--dev refuses to run with REFLEX_BACKEND_HOST={host}: developer mode is for localhost only.")
        return 1
    env = {**os.environ, "UC_DEV": "1"}
    print("DEV MODE: auto-restart on code changes, browser sign-ins survive restarts. Never use in production.", flush=True)
    app_dir = WEBUI / "uc_automation"

    def start() -> subprocess.Popen:
        return subprocess.Popen([str(REFLEX), "run", *extra], cwd=WEBUI, env=env)

    def stop(proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()

    def py_changes(_change, path: str) -> bool:
        return path.endswith(".py") and "__pycache__" not in path

    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    proc = start()
    try:
        # rxconfig.py is in WEBUI, the app in WEBUI/uc_automation; poll so a crashed child is restarted too.
        for changes in watch(app_dir, WEBUI / "rxconfig.py", watch_filter=py_changes, debounce=1500,
                             rust_timeout=2000, yield_on_timeout=True, raise_interrupt=False):
            if changes or proc.poll() is not None:
                what = "changed" if changes else "exited"
                print(f"DEV MODE: {what}, restarting ...", flush=True)
                stop(proc)
                proc = start()
    except KeyboardInterrupt:
        pass
    finally:
        stop(proc)
    return 0


def main() -> int:
    args = sys.argv[1:]
    if "--setup" in args or "--update" in args or not REFLEX.exists():
        code = setup(upgrade="--update" in args)
        if code:
            return code
    if "--dev" in args:
        return run_dev([a for a in args if a != "--dev"])
    os.chdir(WEBUI)
    if os.name == "nt":
        try:
            return subprocess.run([str(REFLEX), "run"]).returncode
        except KeyboardInterrupt:
            return 0
    os.execv(str(REFLEX), [str(REFLEX), "run"])


if __name__ == "__main__":
    sys.exit(main())
