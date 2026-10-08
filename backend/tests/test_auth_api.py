"""HTTP-level auth tests via FastAPI TestClient."""
from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.config import data_file
from backend.main import app
from backend.state import get_session

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    for f in ["21_Users.csv", "13_Employee_Time.csv", "12_Time_Account_Detail.csv"]:
        shutil.copy(data_file(f), tmp_path / f)
    auth._TOKENS.clear()
    get_session().reset()
    yield
    for f in ["21_Users.csv", "13_Employee_Time.csv", "12_Time_Account_Detail.csv"]:
        shutil.copy(tmp_path / f, data_file(f))
    auth._TOKENS.clear()
    get_session().reset()


def test_chat_requires_auth():
    res = client.post("/api/chat", json={"message": "balance?"})
    assert res.status_code == 401


def test_login_then_chat():
    token = client.post("/api/login", json={"username": "weiling", "password": "password"}).json()["token"]
    res = client.post("/api/chat", json={"message": "what is my leave balance?"},
                      headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert "Annual Leave" in res.json()["reply"]


def test_me_returns_logged_in_user():
    token = client.post("/api/login", json={"username": "marcus", "password": "password"}).json()["token"]
    res = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["user_id"] == "E004"


def test_identity_drives_session_user():
    # Logging in as Marcus (E004) pins the session to E004, not the default E005.
    token = client.post("/api/login", json={"username": "marcus", "password": "password"}).json()["token"]
    client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert get_session().session_user_id == "E004"


def test_bad_login_401():
    res = client.post("/api/login", json={"username": "weiling", "password": "wrong"})
    assert res.status_code == 401
