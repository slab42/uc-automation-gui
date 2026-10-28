"""Repo-relative locations shared by the backend modules."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CREDENTIALS_PATH = REPO_ROOT / ".env" / "credentials.env"
CUCM_SCHEMA_DIR = REPO_ROOT / "cucm" / "schema"
WEBUI_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = WEBUI_ROOT / "logs"
