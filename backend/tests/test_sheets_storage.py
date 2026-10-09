"""Sheets persistence contract tests. No credentials or live workbook mutations."""
import copy
import csv
from datetime import date
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import agent, auth, config, email_service, storage
from backend.google_sheets import EPOCH, SheetsStore
from backend.main import app
from backend.state import get_session
from backend.tools import actions, hr, leave_queries


class FakeSheets:
    """Small stateful REST fake with atomic batch application and failure injection."""
    def __init__(self):
        self.sheets = {}
        self.calls = []
        self.fail = None
        self.timeout_after_commit = False
        for sheet_id, name in enumerate(storage.TABLES):
            if name == storage.TOKEN_FILE:
                values = [storage.TOKEN_HEADER]
            else:
                with open(config.data_file(name), newline="", encoding="utf-8") as fh:
                    values = list(csv.reader(fh))
            self.sheets[sheet_id] = {"title": Path(name).stem, "values": copy.deepcopy(values)}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, copy.deepcopy(kwargs)))
        if self.fail:
            return SimpleNamespace(status_code=self.fail, json=lambda: {"error": "private detail"})
        if method == "GET" and url.endswith("/values:batchGet"):
            values = []
            for title in kwargs["params"]["ranges"]:
                title = title[1:-1].replace("''", "'")
                sheet = next(s for s in self.sheets.values() if s["title"] == title)
                values.append({"values": copy.deepcopy(sheet["values"])})
            payload = {"valueRanges": values}
        elif method == "GET":
            payload = {"sheets": [{"properties": {"sheetId": sid, "title": s["title"]}}
                                  for sid, s in self.sheets.items()]}
        else:
            updated = copy.deepcopy(self.sheets)
            for request in kwargs["json"]["requests"]:
                if "addSheet" in request:
                    prop = request["addSheet"]["properties"]
                    assert prop["sheetId"] not in updated
                    updated[prop["sheetId"]] = {"title": prop["title"], "values": []}
                elif "appendCells" in request:
                    data = request["appendCells"]
                    updated[data["sheetId"]]["values"].extend([
                        [next(iter(cell["userEnteredValue"].values())) for cell in r["values"]] for r in data["rows"]])
                else:
                    data = request["updateCells"]
                    pos = data["start"]
                    rows = updated[pos["sheetId"]]["values"]
                    row = rows[pos["rowIndex"]]
                    while len(row) <= pos["columnIndex"]:
                        row.append("")
                    row[pos["columnIndex"]] = next(iter(data["rows"][0]["values"][0]["userEnteredValue"].values()))
            self.sheets = updated
            if self.timeout_after_commit:
                raise TimeoutError()
            payload = {}
        return SimpleNamespace(status_code=200, json=lambda: payload)

    def table(self, name):
        return next(s for s in self.sheets.values() if s["title"] == Path(name).stem)["values"]

    def posts(self):
        return [c for c in self.calls if c[0] == "POST"]


@pytest.fixture
def sheets(tmp_path, monkeypatch):
    shutil.copytree(config.DATA_DIR, tmp_path / "data")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    fake = FakeSheets()
    store = SheetsStore("test-workbook", fake)
    monkeypatch.setattr(config, "DATA_BACKEND", "google_sheets")
    monkeypatch.setattr(storage, "provider", lambda: store)
    actions._invalidate_caches()
    session = get_session()
    session.reset()
    session.session_user_id = "E005"
    class Today(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 9)
    monkeypatch.setattr(hr, "date", Today)
    monkeypatch.setattr(email_service, "_smtp_configured", lambda: False)
    yield fake, store, session
    actions._invalidate_caches()
    auth._TOKENS.clear()
    session.reset()


def submit(session):
    session.employee_confirmed = True
    result = actions.submit_leave_request("CL", "2026-11-17", "2026-11-18", reason="=not a formula")
    assert result["success"]
    return result["employee_time_id"]


def test_one_read_snapshot_per_operation_and_fresh_next_operation(sheets):
    fake, store, session = sheets
    with storage.operation():
        hr.get_entitlements()
        leave_queries.get_employee_leave_requests()
        actions.list_pending_for_approver("E004")
    reads = [c for c in fake.calls if c[1].endswith("/values:batchGet")]
    assert len(reads) == 1
    table = fake.table(actions.EMPLOYEE_TIME)
    pending = next(r for r in table[1:] if r[0] == "R009")
    pending[table[0].index("approval_status")] = "Rejected"
    assert hr.get_entitlements()["pending_request_count"] == 0


def test_submission_and_approval_survive_new_backend_and_session(sheets, monkeypatch):
    fake, store, session = sheets
    local_before = config.data_file(actions.EMPLOYEE_TIME).read_bytes()
    eid = submit(session)
    email = email_service.send_approval_email(eid)
    token = email["approve_url"].split("/api/approval/")[1].split("?")[0]
    assert len(fake.table(storage.TOKEN_FILE)) == 3
    assert token not in str(fake.table(storage.TOKEN_FILE))
    # Simulate a restart: remove all session tokens and construct a new adapter.
    session.reset()
    monkeypatch.setattr(storage, "provider", lambda: SheetsStore("test-workbook", fake))
    assert actions.get_request_status(eid)["requests"][0]["status"] == "Pending"
    posts_before = len(fake.posts())
    assert actions.handle_approval_token(token, "approve")["success"]
    assert len(fake.posts()) == posts_before + 1
    changes = fake.posts()[-1][2]["json"]["requests"]
    changed_sheets = {r["updateCells"]["start"]["sheetId"] if "updateCells" in r else r["appendCells"]["sheetId"] for r in changes}
    assert changed_sheets == {storage.TABLES.index(n) for n in (actions.EMPLOYEE_TIME, actions.ACCOUNT_DETAIL, storage.TOKEN_FILE)}
    session.reset()
    assert actions.get_request_status(eid)["requests"][0]["status"] == "Approved"
    assert not actions.handle_approval_token(token, "approve")["success"]
    assert config.data_file(actions.EMPLOYEE_TIME).read_bytes() == local_before
    _, ledger = actions._read_rows(actions.ACCOUNT_DETAIL)
    assert len([r for r in ledger if r["employee_time_id"] == eid]) == 1


def test_sheet_dates_numbers_and_literal_free_text(sheets):
    fake, store, session = sheets
    eid = submit(session)
    table = fake.table(actions.EMPLOYEE_TIME)
    row = next(r for r in table[1:] if r[0] == eid)
    assert row[table[0].index("start_date")] == (date(2026, 11, 17) - EPOCH).days
    assert row[table[0].index("quantity_in_days")] == 2
    last = fake.posts()[-1][2]["json"]["requests"][-1]["appendCells"]["rows"][0]["values"]
    assert last[table[0].index("reason")] == {"userEnteredValue": {"stringValue": "=not a formula"}}
    assert actions.get_request_status(eid)["requests"][0]["start_date"] == "2026-11-17"


def test_failure_rolls_back_workflow_and_does_not_claim_submission(sheets):
    fake, store, session = sheets
    original = copy.deepcopy(fake.sheets)
    original_commit = store.commit
    def fail_commit(*args):
        fake.fail = 503
        return original_commit(*args)
    store.commit = fail_commit
    with pytest.raises(storage.StorageError, match="HTTP 503"):
        submit(session)
    assert fake.sheets == original
    assert session.reference_id is None
    assert not any("Saved request" in e["message"] for e in session.activity)


def test_uncertain_approval_is_not_automatically_retried(sheets):
    fake, store, session = sheets
    eid = submit(session)
    fake.timeout_after_commit = True
    with pytest.raises(storage.StorageError, match="Refresh request status"):
        actions.handle_ui_decision(eid, "approve", approver_id="E004")
    fake.timeout_after_commit = False
    assert actions.get_request_status(eid)["requests"][0]["status"] == "Approved"
    assert not actions.handle_ui_decision(eid, "approve", approver_id="E004")["success"]
    assert len([r for r in actions._read_rows(actions.ACCOUNT_DETAIL)[1] if r["employee_time_id"] == eid]) == 1


def test_read_failure_returns_503_without_empty_queue_or_csv_fallback(sheets):
    fake, store, session = sheets
    fake.fail = 403
    auth._TOKENS["manager"] = "E004"
    response = TestClient(app).get("/api/pending-approvals", headers={"Authorization": "Bearer manager"})
    assert response.status_code == 503
    assert "pending" not in response.json()
    assert "private detail" not in response.text


def test_registration_persists_after_session_restart(sheets, monkeypatch):
    fake, store, session = sheets
    assert auth.register("persistent-user", "test-only", "E006")["success"]
    session.reset()
    auth._TOKENS.clear()
    monkeypatch.setattr(storage, "provider", lambda: SheetsStore("test-workbook", fake))
    assert auth.login("persistent-user", "test-only")["success"]
    assert "test-only" not in str(fake.table("21_Users.csv"))


def test_missing_table_requires_explicit_setup_and_seeding_preserves_existing(sheets):
    fake, store, session = sheets
    token_sid = storage.TABLES.index(storage.TOKEN_FILE)
    del fake.sheets[token_sid]
    before = copy.deepcopy(fake.sheets)
    with pytest.raises(storage.StorageError, match="Missing worksheet"):
        store.read_all()
    assert not fake.posts()
    assert store.seed_missing() == ["22_Approval_Tokens"]
    for sid, value in before.items():
        assert fake.sheets[sid] == value
    assert store.read_all()[storage.TOKEN_FILE] == (storage.TOKEN_HEADER, [])
    assert store.seed_missing() == []


def test_schema_mismatch_and_formula_errors_fail_visibly(sheets):
    fake, store, session = sheets
    table = fake.table(actions.EMPLOYEE_TIME)
    table[0][0] = "wrong-header"
    with pytest.raises(storage.StorageError, match="missing columns"):
        store.read_all()
    table[0][0] = "employee_time_id"
    table[1][table[0].index("quantity_in_days")] = "#REF!"
    with pytest.raises(storage.StorageError, match="formula error"):
        store.read_all()


def test_updates_preserve_extra_columns_and_unchanged_cells(sheets):
    fake, store, session = sheets
    table = fake.table(actions.EMPLOYEE_TIME)
    table[0].append("formula_result")
    for row in table[1:]:
        row.append("computed")
    assert actions.handle_ui_decision("R009", "reject", approver_id="E004")["success"]
    changes = fake.posts()[-1][2]["json"]["requests"]
    assert {c["updateCells"]["start"]["columnIndex"] for c in changes} == {
        table[0].index("approval_status"), table[0].index("decided_at"), table[0].index("decision_note")}
    assert all(row[-1] == "computed" for row in fake.table(actions.EMPLOYEE_TIME)[1:])


def test_token_action_cannot_be_changed(sheets):
    fake, store, session = sheets
    eid = submit(session)
    email = email_service.send_approval_email(eid)
    token = email["approve_url"].split("/api/approval/")[1].split("?")[0]
    assert not actions.handle_approval_token(token, "reject")["success"]
    assert actions.get_request_status(eid)["requests"][0]["status"] == "Pending"


def test_concurrent_submissions_are_serialized(sheets):
    from concurrent.futures import ThreadPoolExecutor
    fake, store, session = sheets
    session.employee_confirmed = True
    def request():
        return actions.submit_leave_request("CL", "2026-11-17", "2026-11-18")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: request(), range(2)))
    assert sum(r["success"] for r in results) == 1
    assert len(fake.posts()) == 1


def test_renamed_tabs_use_explicit_mapping(sheets):
    fake, store, session = sheets
    sid = storage.TABLES.index(actions.EMPLOYEE_TIME)
    fake.sheets[sid]["title"] = "Team's Requests"
    custom = SheetsStore("test-workbook", fake, {actions.EMPLOYEE_TIME: "Team's Requests"})
    assert custom.read_all()[actions.EMPLOYEE_TIME][1]
    assert "'Team''s Requests'" in fake.calls[-1][2]["params"]["ranges"]


def test_blank_rows_preserve_update_coordinates(sheets):
    fake, store, session = sheets
    table = fake.table(actions.EMPLOYEE_TIME)
    table.insert(1, [])
    assert actions.handle_ui_decision("R009", "reject", approver_id="E004")["success"]
    table = fake.table(actions.EMPLOYEE_TIME)
    row = next(r for r in table[1:] if r and r[0] == "R009")
    assert row[table[0].index("approval_status")] == "Rejected"
    assert table[1] == []


def test_bad_date_is_reported_during_readiness_check(sheets):
    fake, store, session = sheets
    table = fake.table(actions.EMPLOYEE_TIME)
    table[1][table[0].index("start_date")] = "not a date"
    with pytest.raises(storage.StorageError, match="native dates or YYYY-MM-DD"):
        store.read_all()


def test_service_account_json_loader_does_not_expose_credentials(monkeypatch):
    pytest.importorskip("google.auth")
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.service_account import Credentials
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import json
    # A throwaway test key; no external request or real account is used.
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", json.dumps({
        "type": "service_account", "client_email": "test@example.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token", "private_key": pem}))
    monkeypatch.setattr(config, "GOOGLE_SHEETS_SPREADSHEET_ID", "test-workbook")
    store = SheetsStore.from_config()
    assert isinstance(store.session, AuthorizedSession)
    assert isinstance(store.session.credentials, Credentials)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "PRIVATE-invalid-json")
    with pytest.raises(storage.StorageError) as error:
        SheetsStore.from_config()
    assert "PRIVATE-invalid-json" not in str(error.value)


def test_startup_validates_storage_and_health_reports_backend(sheets):
    with TestClient(app) as client:
        assert client.get("/api/health").json()["data_backend"] == "google_sheets"


def test_startup_rejects_missing_remote_tables(sheets):
    fake, store, session = sheets
    del fake.sheets[storage.TABLES.index(storage.TOKEN_FILE)]
    with pytest.raises(storage.StorageError, match="Missing worksheet"):
        with TestClient(app):
            pass


@pytest.mark.parametrize('decision,broken', [('approve', False), ('approve', True), ('reject', False)])
def test_forecast_and_persistent_ui_decision(sheets, monkeypatch, tmp_path, decision, broken):
    from backend import main, leave_forecast
    fake, store, session = sheets
    eid = submit(session)
    _, people = actions._read_rows('02_Job_Information.csv')
    name = next(p['full_name'] for p in people if p['user_id'] == 'E005')
    path = tmp_path / 'forecast.csv'
    with path.open('w', newline='') as handle:
        csv.writer(handle).writerows([['Named Resource', 'Nov-26'], [name, '']])
    monkeypatch.setattr(config, 'LEAVE_FORECAST_CSV', str(path))
    if broken:
        monkeypatch.setattr(leave_forecast.CsvBackend, 'write_cell', lambda *args: (_ for _ in ()).throw(OSError('unavailable')))
    monkeypatch.setattr(main, '_require_identity', lambda token: 'E004')
    sent = []
    def notify(request_id, **kwargs):
        assert actions.get_request_status(request_id)['requests'][0]['status'] == ('Approved' if decision == 'approve' else 'Rejected')
        sent.append(request_id)
        return {'sent': True}
    monkeypatch.setattr(email_service, 'send_confirmation_email', notify)
    monkeypatch.setattr(email_service, 'send_rejection_email', notify)
    result = main.ui_approval(main.UIApproval(employee_time_id=eid, action=decision))
    assert result['success'] and result['employee_emailed']
    assert sent == [eid]
    if decision == 'approve':
        assert result['forecast_status'] == ('failed' if broken else 'updated')
        if not broken:
            assert '17-18 (CL)' in path.read_text()
            assert leave_forecast.record_approved_leave(eid)['status'] == 'unchanged'
    else:
        assert 'forecast_status' not in result
        assert '(CL)' not in path.read_text()
    assert not main.ui_approval(main.UIApproval(employee_time_id=eid, action=decision))['success']
    assert sent == [eid]


def test_forecast_uses_shared_google_credentials(monkeypatch):
    import gspread
    from types import SimpleNamespace
    from backend import google_sheets, leave_forecast
    credentials = object()
    sheet = SimpleNamespace(title='Forecast')
    book = SimpleNamespace(title='Leave', worksheet=lambda name: sheet)
    monkeypatch.setattr(google_sheets, 'load_credentials', lambda: credentials)
    def authorize(actual):
        assert actual is credentials
        return SimpleNamespace(open_by_key=lambda key: book)
    monkeypatch.setattr(gspread, 'authorize', authorize)
    assert leave_forecast.GoogleSheetBackend('workbook', 'Forecast').ws is sheet
