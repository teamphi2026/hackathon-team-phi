"""Email service + token management — Task 6.

- Single-use approve/reject tokens (UUID), stored in session.approval_token_map
  with a 24h expiry.
- send_approval_email(employee_time_id)   -> manager, with Approve/Reject links
- send_confirmation_email(employee_time_id) -> employee, with reference id
- send_rejection_email(employee_time_id, reason) -> employee

SMTP (Gmail app password) is the default transport. When no credentials are
configured the service runs in DRY-RUN mode: the email is logged and returned
instead of being sent, so the app stays runnable and testable without secrets.
"""
from __future__ import annotations

import smtplib
import uuid
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from . import config
from .state import get_session
from .tools import actions, hr
from .tools import team_project as tp

TOKEN_TTL = timedelta(hours=24)


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

def _new_token(employee_time_id: str, action: str) -> str:
    token = uuid.uuid4().hex
    get_session().approval_token_map[token] = {
        "employee_time_id": employee_time_id,
        "action": action,
        "expiry": datetime.now() + TOKEN_TTL,
        "used": False,
    }
    return token


def _approval_link(token: str, action: str) -> str:
    return f"{config.APP_BASE_URL}/api/approval/{token}?action={action}"


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

def _smtp_configured() -> bool:
    return bool(config.SMTP_USER and config.SMTP_PASSWORD and config.EMAIL_FROM)


def _send(to_addr: str, subject: str, html: str) -> dict[str, Any]:
    """Send an HTML email, or log it in dry-run mode when SMTP is unconfigured."""
    if not _smtp_configured():
        get_session().log_activity("ok", f"[DRY-RUN email] to={to_addr} subject={subject!r}")
        return {"sent": False, "dry_run": True, "to": to_addr, "subject": subject, "html": html}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_FROM
    msg["To"] = to_addr
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.starttls()
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.sendmail(config.EMAIL_FROM, [to_addr], msg.as_string())
        return {"sent": True, "dry_run": False, "to": to_addr, "subject": subject}
    except Exception as exc:  # pragma: no cover - network failure path
        get_session().log_activity("conflict", f"Email send failed: {exc}")
        return {"sent": False, "dry_run": False, "error": str(exc), "to": to_addr}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def _request_row(employee_time_id: str) -> dict[str, str] | None:
    _, rows = actions._read_rows(actions.EMPLOYEE_TIME)
    return next((r for r in rows if r["employee_time_id"] == employee_time_id), None)


def _employee(uid: str) -> dict[str, str]:
    _, rows = actions._read_rows("02_Job_Information.csv")
    return next((r for r in rows if r["user_id"] == uid), {})


# ---------------------------------------------------------------------------
# Email builders / senders
# ---------------------------------------------------------------------------

def send_approval_email(employee_time_id: str) -> dict[str, Any]:
    """Generate approve/reject tokens and email the manager."""
    req = _request_row(employee_time_id)
    if req is None:
        return {"sent": False, "error": f"Request {employee_time_id} not found."}

    employee = _employee(req["user_id"])
    manager = _employee(req["approver_id"])
    manager_email = manager.get("email", "")

    approve_token = _new_token(employee_time_id, "approve")
    reject_token = _new_token(employee_time_id, "reject")
    approve_url = _approval_link(approve_token, "approve")
    reject_url = _approval_link(reject_token, "reject")

    # Coverage summary for the request window (manager context).
    coverage = tp.check_coverage(req["start_date"], req["end_date"])
    cover_lines = "".join(
        f"<li>{t['team_name']}: {t['on_duty']} on duty / min {t['min_required']} "
        f"({t['status']})</li>"
        for t in coverage["teams"]
    )

    html = f"""
    <h2>Leave approval request</h2>
    <p><b>{employee.get('full_name', req['user_id'])}</b> has requested leave:</p>
    <ul>
      <li>Type: {req['time_type_code']}</li>
      <li>Dates: {req['start_date']} to {req['end_date']}</li>
      <li>Working days: {req['quantity_in_days']}</li>
      <li>Reason: {req.get('reason') or '—'}</li>
    </ul>
    <p>Team coverage during this period:</p>
    <ul>{cover_lines}</ul>
    <p>
      <a href="{approve_url}" style="padding:10px 18px;background:#2e7d32;color:#fff;
         text-decoration:none;border-radius:4px;">Approve</a>
      &nbsp;&nbsp;
      <a href="{reject_url}" style="padding:10px 18px;background:#c62828;color:#fff;
         text-decoration:none;border-radius:4px;">Reject</a>
    </p>
    <p style="color:#888;font-size:12px;">These links are single-use and expire in 24 hours.</p>
    """
    result = _send(manager_email, f"Leave approval needed — {req['start_date']} to {req['end_date']}", html)
    result.update(
        {"manager_email": manager_email, "approve_url": approve_url, "reject_url": reject_url}
    )
    get_session().log_activity("ok", f"Approval email prepared for {manager_email}")
    return result


def send_confirmation_email(employee_time_id: str) -> dict[str, Any]:
    """Email the employee that their leave is approved, with the reference id."""
    req = _request_row(employee_time_id)
    if req is None:
        return {"sent": False, "error": f"Request {employee_time_id} not found."}
    employee = _employee(req["user_id"])
    html = f"""
    <h2>Your leave is approved</h2>
    <p>Hi {employee.get('full_name', '')},</p>
    <p>Your leave request has been approved.</p>
    <ul>
      <li>Reference: <b>{employee_time_id}</b></li>
      <li>Type: {req['time_type_code']}</li>
      <li>Dates: {req['start_date']} to {req['end_date']}</li>
      <li>Working days: {req['quantity_in_days']}</li>
    </ul>
    """
    return _send(employee.get("email", ""), f"Leave approved — {employee_time_id}", html)


def send_rejection_email(employee_time_id: str, reason: str = "") -> dict[str, Any]:
    """Email the employee that their leave was rejected."""
    req = _request_row(employee_time_id)
    if req is None:
        return {"sent": False, "error": f"Request {employee_time_id} not found."}
    employee = _employee(req["user_id"])
    html = f"""
    <h2>Your leave request was not approved</h2>
    <p>Hi {employee.get('full_name', '')},</p>
    <p>Your leave request <b>{employee_time_id}</b> ({req['start_date']} to
       {req['end_date']}) was not approved.</p>
    <p>{('Reason: ' + reason) if reason else ''}</p>
    <p>No leave balance has been deducted.</p>
    """
    return _send(employee.get("email", ""), f"Leave not approved — {employee_time_id}", html)
