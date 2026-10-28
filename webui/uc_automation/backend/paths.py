"""Repo-relative locations shared by the backend modules."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CREDENTIALS_PATH = REPO_ROOT / ".env" / "credentials.env"
WEBUI_ROOT = Path(__file__).resolve().parents[2]
# API schemas shipped with the webui, one folder per platform: schemas/<platform>/<version>/
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"
CUCM_SCHEMA_DIR = SCHEMA_DIR / "cucm"
CUC_SCHEMA_DIR = SCHEMA_DIR / "cuc"
LOG_DIR = WEBUI_ROOT / "logs"
