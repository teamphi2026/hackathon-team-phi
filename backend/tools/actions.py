"""Action tools (controlled writes) + approval state machine — Task 5.

State machine:
    DRAFT -> EMPLOYEE_CONFIRMED -> PENDING_MANAGER_APPROVAL
          -> APPROVED / REJECTED -> SUBMITTED

Enforced in application code only. The LLM never mutates approval_status or
employee_confirmed. Guardrails:
  - submit_leave_request requires session.employee_confirmed == True
  - handle_approval_token is idempotent (single-use tokens) and only acts on
    rows in PENDING_MANAGER_APPROVAL
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .. import storage
from ..state import get_session
from . import hr
from . import team_project as tp

EMPLOYEE_TIME = "13_Employee_Time.csv"
ACCOUNT_DETAIL = "12_Time_Account_Detail.csv"

_LEAVE_TO_ACCOUNT = {
    "AL": "ACC_AL",
    "OIL": "ACC_OIL",
    "SL": "ACC_SL",
    "HL": "ACC_HL",
    "CL": "ACC_CL",
}


# ---------------------------------------------------------------------------
# Low-level CSV helpers (append-only writes, cache-aware)
# ---------------------------------------------------------------------------

def _read_rows(name: str) -> tuple[list[str], list[dict[str, str]]]:
    return storage.read_rows(name)


def _write_rows(name: str, header: list[str], rows: list[dict[str, str]]) -> None:
    storage.write_rows(name, header, rows)
    _invalidate_caches()


def _append_row(name: str, row: dict[str, str]) -> None:
    header, rows = _read_rows(name)
    rows.append(row)
    _write_rows(name, header, rows)


def _invalidate_caches() -> None:
    """Drop cached DataFrames so reads reflect the new writes."""
    hr._load.cache_clear()
    tp._load.cache_clear()
    get_session().entitlements = None


def _next_id(name: str, id_field: str, prefix: str) -> str:
    _, rows = _read_rows(name)
    nums = []
    for r in rows:
        val = r.get(id_field, "")
        if val.startswith(prefix):
            try:
                nums.append(int(val[len(prefix):]))
            except ValueError:
                continue
    nxt = (max(nums) + 1) if nums else 1
    width = max(3, len(str(nxt)))
    return f"{prefix}{nxt:0{width}d}"


# ---------------------------------------------------------------------------
# submit_leave_request
# ---------------------------------------------------------------------------

@storage.mutation
def submit_leave_request(
    leave_type: str,
    start_date: str,
    end_date: str,
    half_day: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    """Write a Pending Employee_Time row. Precondition: employee_confirmed.

    Does NOT send email — that is a separate step (email_service).
    """
    session = get_session()
    if not session.employee_confirmed:
        return {
            "success": False,
            "error": "Cannot submit: employee has not confirmed the request.",
        }

    # Re-validate at submit time (REQ-006).
    validation = hr.validate_policy(leave_type, start_date, end_date, half_day)
    if not validation["valid"]:
        return {
            "success": False,
            "error": "Validation failed at submit time.",
            "violations": validation["violations"],
        }

    profile = hr.get_employee_profile()
    new_id = _next_id(EMPLOYEE_TIME, "employee_time_id", "R")
    row = {
        "employee_time_id": new_id,
        "user_id": session.session_user_id,
        "time_type_code": leave_type,
        "start_date": start_date,
        "end_date": end_date,
        "half_day": half_day or "None",
        "quantity_in_days": str(validation["working_days"]),
        "reason": reason,
        "approval_status": "Pending",
        "approver_id": profile["manager_id"],
        "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "decided_at": "",
        "decision_note": "",
    }
    _append_row(EMPLOYEE_TIME, row)

    session.employee_time_id = new_id
    session.approval_status = "PENDING_MANAGER_APPROVAL"
    session.reference_id = new_id
    session.log_activity("ok", f"Saved request {new_id}; it's now waiting for your manager's approval")

    return {
        "success": True,
        "employee_time_id": new_id,
        "status": "Pending",
        "working_days": validation["working_days"],
        "approver_id": profile["manager_id"],
    }


# ---------------------------------------------------------------------------
# handle_approval_token
# ---------------------------------------------------------------------------

@storage.mutation
def handle_approval_token(token: str, action: str | None = None) -> dict[str, Any]:
    """Apply a manager decision via a single-use token.

    Called by the token callback endpoint, never by the LLM. Idempotent:
    a used or expired token returns an error with no state change.
    """
    session = get_session()
    tokens = session.approval_token_map
    from .. import approval_tokens
    entry = approval_tokens.lookup(token) if storage.using_sheets() else tokens.get(token)

    if entry is None:
        return {"success": False, "message": "Invalid token."}
    if entry.get("used"):
        return {"success": False, "message": "This token has already been used."}
    expiry = entry.get("expiry")
    if expiry and datetime.now() > expiry:
        return {"success": False, "message": "This approval link has expired."}

    resolved_action = (action or entry.get("action") or "").lower()
    if resolved_action not in ("approve", "reject"):
        return {"success": False, "message": f"Unknown action: {resolved_action!r}"}

    employee_time_id = entry["employee_time_id"]
    header, rows = _read_rows(EMPLOYEE_TIME)
    target = next((r for r in rows if r["employee_time_id"] == employee_time_id), None)
    if target is None:
        return {"success": False, "message": f"Request {employee_time_id} not found."}
    if target["approval_status"] != "Pending":
        return {
            "success": False,
            "message": f"Request {employee_time_id} is not pending (currently {target['approval_status']}).",
        }

    if action and action.lower() != entry.get("action"):
        return {"success": False, "message": "This token does not authorise that action."}
    # Sheets token consumption commits atomically with the decision and debit.
    if storage.using_sheets():
        approval_tokens.consume(token)
    entry["used"] = True

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if resolved_action == "approve":
        target["approval_status"] = "Approved"
        target["decided_at"] = now
        _write_rows(EMPLOYEE_TIME, header, rows)
        _write_debit_row(target)
        session.approval_status = "SUBMITTED"
        session.log_activity("ok", f"Request {employee_time_id} approved and the leave balance updated")
        return {"success": True, "action": "approve", "employee_time_id": employee_time_id,
                "message": f"Request {employee_time_id} approved."}
    else:
        target["approval_status"] = "Rejected"
        target["decided_at"] = now
        target["decision_note"] = "Rejected by manager"
        _write_rows(EMPLOYEE_TIME, header, rows)
        session.approval_status = "REJECTED"
        session.log_activity("conflict", f"Request {employee_time_id} was rejected, so no leave was deducted")
        return {"success": True, "action": "reject", "employee_time_id": employee_time_id,
                "message": f"Request {employee_time_id} rejected."}


def get_request_status(reference_id: str | None = None) -> dict[str, Any]:
    from .leave_queries import get_request_status as lookup
    return lookup(reference_id)


def list_pending_for_approver(approver_id: str) -> list[dict[str, Any]]:
    from .leave_queries import pending_manager_rows
    return pending_manager_rows(approver_id)


@storage.mutation
def handle_ui_decision(employee_time_id: str, action: str,
                       approver_id: str | None = None) -> dict[str, Any]:
    """Apply a manager decision made in the UI card (no email token).

    Same guarantees as handle_approval_token: only acts on a Pending row,
    writes a debit on approve, and is a no-op if already decided. When
    `approver_id` is given, only that request's assigned approver may decide.
    """
    session = get_session()
    resolved = (action or "").lower()
    if resolved not in ("approve", "reject"):
        return {"success": False, "message": f"Unknown action: {action!r}"}

    header, rows = _read_rows(EMPLOYEE_TIME)
    target = next((r for r in rows if r["employee_time_id"] == employee_time_id), None)
    if target is None:
        return {"success": False, "message": f"Request {employee_time_id} not found."}
    if approver_id is not None and target["approver_id"] != approver_id:
        return {"success": False, "message": "You are not the approver for this request."}
    if target["approval_status"] != "Pending":
        return {"success": False,
                "message": f"Request {employee_time_id} is not pending (currently {target['approval_status']})."}

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if resolved == "approve":
        target["approval_status"] = "Approved"
        target["decided_at"] = now
        _write_rows(EMPLOYEE_TIME, header, rows)
        _write_debit_row(target)
        session.approval_status = "SUBMITTED"
        session.log_activity("ok", f"Request {employee_time_id} approved and the leave balance updated")
        return {"success": True, "action": "approve", "employee_time_id": employee_time_id,
                "message": f"Request {employee_time_id} approved."}
    target["approval_status"] = "Rejected"
    target["decided_at"] = now
    target["decision_note"] = "Rejected by manager"
    _write_rows(EMPLOYEE_TIME, header, rows)
    session.approval_status = "REJECTED"
    session.log_activity("conflict", f"Request {employee_time_id} was rejected, so no leave was deducted")
    return {"success": True, "action": "reject", "employee_time_id": employee_time_id,
            "message": f"Request {employee_time_id} rejected."}


def _write_debit_row(request_row: dict[str, str]) -> None:
    """Write the Time_Account_Detail debit for an approved request."""
    leave_type = request_row["time_type_code"]
    acc_type = _LEAVE_TO_ACCOUNT.get(leave_type)
    uid = request_row["user_id"]

    # Resolve the user's account id for this leave type.
    _, ta_rows = _read_rows("11_Time_Account.csv")
    account_id = next(
        (r["time_account_id"] for r in ta_rows
         if r["user_id"] == uid and r["time_account_type_code"] == acc_type),
        "",
    )

    qty = float(request_row["quantity_in_days"])
    detail_id = _next_id(ACCOUNT_DETAIL, "detail_id", "D")
    row = {
        "detail_id": detail_id,
        "time_account_id": account_id,
        "booking_date": request_row["start_date"],
        "posting_type": "Employee Time",
        "booking_amount": str(-qty),
        "booking_unit": "DAYS",
        "employee_time_id": request_row["employee_time_id"],
        "comment": f"Booking for {request_row['employee_time_id']}",
        "expiry_date": "",
        "consumes_detail_id": "",
        "remaining_credit": "",
        "credit_status": "",
    }
    _append_row(ACCOUNT_DETAIL, row)
