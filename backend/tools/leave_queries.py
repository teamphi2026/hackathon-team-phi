"""Live, read-only leave queries shared by chat, balances and the approval panel.

Employee_Time is authoritative for request status. Identity arguments on private
helpers are server-side only; public chat tools obtain identity from the session.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from ..state import get_session

PENDING = "Pending"
APPROVED = "Approved"
STATUSES = {PENDING, APPROVED, "Rejected", "Cancelled"}


def _rows(name: str) -> list[dict[str, str]]:
    from .actions import _read_rows
    return _read_rows(name)[1]


def employee_request_rows(employee_id: str) -> list[dict[str, str]]:
    """Uncached authoritative rows; for internal, trusted callers only."""
    return [r for r in _rows("13_Employee_Time.csv") if r["user_id"] == employee_id]


def _shape(row: dict[str, str], names: dict[str, str]) -> dict[str, Any]:
    from .hr import format_date_range
    result = {
        "reference_id": row["employee_time_id"],
        "leave_type": row["time_type_code"],
        "start_date": row["start_date"], "end_date": row["end_date"],
        "date_label": format_date_range(date.fromisoformat(row["start_date"]),
                                         date.fromisoformat(row["end_date"])),
        "working_days": row["quantity_in_days"], "status": row["approval_status"],
        "submitted_at": row.get("submitted_at", ""), "decided_at": row.get("decided_at", ""),
    }
    if row["approval_status"] == PENDING:
        result["awaiting_approval_from"] = names.get(row["approver_id"], "Assigned manager")
    return result


def _names() -> dict[str, str]:
    return {p["user_id"]: p["full_name"] for p in _rows("02_Job_Information.csv")}


def get_employee_leave_requests(status: str | None = None,
                                reference_id: str | None = None) -> dict[str, Any]:
    """All matching personal requests, without a history limit hiding pending rows."""
    if status is not None and status not in STATUSES:
        raise ValueError("Unknown leave status")
    rows = employee_request_rows(get_session().session_user_id)
    names = _names()
    pending_count = sum(r["approval_status"] == PENDING for r in rows)
    if reference_id:
        rows = [r for r in rows if r["employee_time_id"] == reference_id.strip().upper()]
    if status:
        rows = [r for r in rows if r["approval_status"] == status]
    requests = [_shape(r, names) for r in reversed(rows)]
    return {"found": bool(requests), "requests": requests, "count": len(requests),
            "pending_count": pending_count, "scope": "employee"}


def pending_manager_rows(manager_id: str) -> list[dict[str, Any]]:
    """Panel records, authorised by the request's assigned approver field."""
    names = _names()
    out = []
    for r in _rows("13_Employee_Time.csv"):
        if (r["approval_status"] != PENDING or r["approver_id"] != manager_id
                or r["user_id"] == manager_id):
            continue
        out.append({**_shape(r, names),
                    "employee_time_id": r["employee_time_id"], "employee_id": r["user_id"],
                    "employee_name": names.get(r["user_id"], "Team member"),
                    "reason": r.get("reason", ""), "approver_id": r["approver_id"],
                    "approver_name": names.get(r["approver_id"], "Assigned manager")})
    return out


def get_pending_manager_approvals() -> dict[str, Any]:
    """Chat projection of exactly the panel queue, without private free text or ids."""
    rows = pending_manager_rows(get_session().session_user_id)
    private = {"employee_id", "approver_id", "reason"}
    requests = [{k: v for k, v in r.items() if k not in private} for r in rows]
    return {"requests": requests, "count": len(requests), "scope": "manager"}


def is_manager() -> bool:
    uid = get_session().session_user_id
    return (any(p.get("manager_id") == uid for p in _rows("02_Job_Information.csv"))
            or any(r["approver_id"] == uid and r["user_id"] != uid
                   for r in _rows("13_Employee_Time.csv")))


def get_request_status(reference_id: str | None = None) -> dict[str, Any]:
    result = get_employee_leave_requests(reference_id=reference_id)
    # Preserve the existing authority to inspect an assigned request by reference.
    if reference_id and not result["found"]:
        uid = get_session().session_user_id
        names = _names()
        rows = [r for r in _rows("13_Employee_Time.csv")
                if r["employee_time_id"] == reference_id.strip().upper()
                and r["approver_id"] == uid and r["user_id"] != uid]
        result["requests"] = [{**_shape(r, names),
                               "employee_name": names.get(r["user_id"], "Team member")} for r in rows]
        result["found"] = bool(rows)
        result["count"] = len(rows)
    if not result["found"]:
        result["message"] = (f"I couldn't find a request with reference {reference_id.strip().upper()} on your record."
                             if reference_id else "You have no leave requests on record.")
    return result
