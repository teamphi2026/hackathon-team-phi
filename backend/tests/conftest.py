"""Shared pytest fixtures."""
from __future__ import annotations

import shutil

import pytest

from backend import config
from backend.config import data_file
from backend.state import get_session
from backend.tools import actions

# Data files that mutating tests may touch.
MUTABLE_FILES = ["13_Employee_Time.csv", "12_Time_Account_Detail.csv"]


@pytest.fixture(autouse=True)
def _deterministic_mode(monkeypatch):
    """Default every test to the deterministic planner.

    A local .env may set real ICA credentials (enabling LLM mode); clearing
    them here keeps the suite offline and reproducible. The LLM-path tests
    re-enable credentials explicitly within their own test bodies.
    """
    monkeypatch.setattr(config, "ICA_API_KEY", "")
    monkeypatch.setattr(config, "ICA_BASE_URL", "")


@pytest.fixture(autouse=True)
def _isolate_email_log(monkeypatch, tmp_path):
    """Keep test runs out of the real logs/email_events.jsonl."""
    from backend import tool_logger
    monkeypatch.setattr(tool_logger, "EMAIL_LOG_FILE", tmp_path / "email_events.jsonl")
    monkeypatch.setattr(tool_logger, "FORECAST_LOG_FILE", tmp_path / "leave_forecast.jsonl")


@pytest.fixture
def isolate_data(tmp_path):
    """Back up and restore the mutable CSVs around a test, pin session to E005."""
    backups = {}
    for f in MUTABLE_FILES:
        shutil.copy(data_file(f), tmp_path / f)
        backups[f] = tmp_path / f
    s = get_session()
    s.reset()
    s.session_user_id = "E005"
    actions._invalidate_caches()
    yield s
    for f, b in backups.items():
        shutil.copy(b, data_file(f))
    actions._invalidate_caches()
    s.reset()
