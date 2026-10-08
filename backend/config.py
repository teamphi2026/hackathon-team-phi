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

# LLM / orchestrator config
ICA_API_KEY = os.getenv("ICA_API_KEY", "")
ICA_BASE_URL = os.getenv("ICA_BASE_URL", "")
ICA_MODEL = os.getenv("ICA_MODEL", "gpt-4o")


def data_file(name: str) -> Path:
    """Return the full path to a CSV in hr_data/ by file name."""
    return DATA_DIR / name
