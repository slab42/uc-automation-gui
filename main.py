#!/usr/bin/env python3
"""Launch the slab42 UC-Automations web UI (Reflex, webui/).

Usage:
    python3 main.py             start the app (UI on http://localhost:3000, backend on :8000)
    python3 main.py --setup     create or refresh webui/.venv from webui/requirements.txt, then exit

The first run creates webui/.venv and installs the requirements. Credentials live in
.env/credentials.env (see webui/credentials.env.EXAMPLE); the Credentials page edits that file.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

WEBUI = Path(__file__).resolve().parent / "webui"
VENV = WEBUI / ".venv"
REQUIREMENTS = WEBUI / "requirements.txt"
REFLEX = VENV / "bin" / "reflex"
PYTHON = VENV / "bin" / "python"


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


def setup() -> int:
    """Create webui/.venv if needed and install the requirements into it."""
    if not PYTHON.exists():
        python = find_python()
        if python is None:
            print("Python 3.10 or newer is required (python3.10 ... python3.14 on PATH).")
            return 1
        print(f"Creating {VENV} with {python} ...")
        subprocess.run([python, "-m", "venv", str(VENV)], check=True)
    print("Installing requirements ...")
    subprocess.run([str(PYTHON), "-m", "pip", "install", "-q", "-r", str(REQUIREMENTS)], check=True)
    return 0


def main() -> int:
    if "--setup" in sys.argv[1:] or not REFLEX.exists():
        code = setup()
        if code or "--setup" in sys.argv[1:]:
            return code
    os.chdir(WEBUI)
    os.execv(str(REFLEX), [str(REFLEX), "run"])


if __name__ == "__main__":
    sys.exit(main())
