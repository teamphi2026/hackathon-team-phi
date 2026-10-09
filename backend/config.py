"""Central configuration and data paths.

Loads environment variables once and resolves the location of the hr_data
CSVs so every tool module reads from a single source of truth.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Repo root is the parent of the backend/ package directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "hr_data"
POLICIES_DIR = REPO_ROOT / "policies"

# Demo session identity. Set server-side only — never accepted from the LLM.
DEMO_USER_ID = os.getenv("DEMO_USER_ID", "E005")

# Email / app config
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")

# Leave forecast Google Sheet (updated after a manager approves leave).
# Leave GOOGLE_SHEET_ID empty to disable the feature.
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip()
GOOGLE_SHEET_TAB = os.getenv("GOOGLE_SHEET_TAB", "").strip()          # worksheet name; blank = first tab
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()   # the key's JSON text
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()   # or a path to the key file
# Local-dev alternative: write to a CSV with the same layout instead of Google (opt-in).
LEAVE_FORECAST_CSV = os.getenv("LEAVE_FORECAST_CSV", "").strip()

# LLM / orchestrator config
ICA_API_KEY = os.getenv("ICA_API_KEY", "").strip()
ICA_MODEL = os.getenv("ICA_MODEL", "gpt-5.4").strip()


def _normalize_base_url(raw: str) -> str:
    """Normalize the ICA base URL for the OpenAI-compatible client.

    Strips whitespace/trailing slashes and ensures the OpenAI client's
    required `/v1` suffix is present (the IBM endpoint 404s without it).
    """
    url = (raw or "").strip().rstrip("/")
    if not url:
        return ""
    if not url.endswith("/v1"):
        url = url + "/v1"
    return url


ICA_BASE_URL = _normalize_base_url(os.getenv("ICA_BASE_URL", ""))


def data_file(name: str) -> Path:
    """Return the full path to a CSV in hr_data/ by file name."""
    return DATA_DIR / name

# Persistence. Sheets mode never silently falls back to ephemeral CSV writes.
DATA_BACKEND = os.getenv("DATA_BACKEND", "csv").strip().lower()
GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip()
# Optional JSON mapping: {"13_Employee_Time.csv": "Employee_Time"}
GOOGLE_SHEETS_TAB_MAP = os.getenv("GOOGLE_SHEETS_TAB_MAP", "{}").strip()
