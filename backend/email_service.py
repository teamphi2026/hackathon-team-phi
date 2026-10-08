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

import logging
import smtplib
import time
import uuid
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from . import config
from .state import get_session
from .tool_logger import log_email
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

SMTP_TIMEOUT_SECONDS = 15


def _is_placeholder(value: str) -> bool:
    """True for template values copied from .env.example / the .env comments."""
    v = (value or "").strip().lower()
    return not v or v.startswith("your-") or "your-gmail" in v or "app-password" in v


def _smtp_configured() -> bool:
    return not any(
        _is_placeholder(v)
        for v in (config.SMTP_USER, config.SMTP_PASSWORD, config.EMAIL_FROM)
    )


def _failure_hint(code: int | None, text: str, stage: str, exc_name: str) -> str:
    """Plain-English next step for the SMTP failures we have actually hit."""
    t = (text or "").lower()
    if code == 525 or "unauthorized ip" in t:
        return "Provider blocks unknown IPs: add this machine's public IP to its authorized-IP list."
    if "smtpclientauthentication is disabled" in t:
        return "SMTP AUTH is disabled for this Microsoft mailbox: use another sender/provider."
    if code in (535, 534, 530) or exc_name == "SMTPAuthenticationError":
        return "Login rejected: check SMTP_USER (login id) and SMTP_PASSWORD (app password / SMTP key)."
    if code in (550, 553, 554) or "sender" in t:
        return "Sender/recipient rejected: EMAIL_FROM must be a verified sender at the provider."
    if exc_name == "SMTPServerDisconnected":
        return f"Server closed the connection during '{stage}': check SMTP_HOST/PORT match the account's provider."
    if exc_name in ("TimeoutError", "socket.timeout", "gaierror", "ConnectionRefusedError", "OSError"):
        return "Network problem reaching SMTP_HOST:SMTP_PORT (firewall, VPN or wrong host)."
    return ""


def _send(to_addr: str, subject: str, html: str, *, kind: str = "email",
          employee_time_id: str = "") -> dict[str, Any]:
    """Send an HTML email, or log it in dry-run mode when SMTP is unconfigured.

    Every outcome is written to logs/email_events.jsonl via log_email. Message
    bodies, passwords and approval tokens are never logged.
    """
    ctx = {
        "kind": kind, "employee_time_id": employee_time_id, "to": to_addr,
        "subject": subject, "from": config.EMAIL_FROM,
        "host": config.SMTP_HOST, "port": config.SMTP_PORT, "smtp_user": config.SMTP_USER,
    }
    if not _smtp_configured():
        log_email("dry_run", {**ctx, "reason": "SMTP_USER/SMTP_PASSWORD/EMAIL_FROM missing or placeholder"},
                  level=logging.WARNING)
        get_session().log_activity(
            "conflict",
            f"[DRY-RUN email — NOT sent: SMTP_USER/SMTP_PASSWORD/EMAIL_FROM not set in .env] "
            f"to={to_addr} subject={subject!r}",
        )
        return {"sent": False, "dry_run": True, "to": to_addr, "subject": subject, "html": html}
    if not to_addr:
        log_email("skipped", {**ctx, "reason": "no recipient address on file"}, level=logging.ERROR)
        get_session().log_activity("conflict", f"Email not sent: no recipient address ({subject!r})")
        return {"sent": False, "dry_run": False, "error": "No recipient address.", "to": to_addr}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_FROM
    msg["To"] = to_addr
    msg.attach(MIMEText(html, "html"))

    log_email("attempt", ctx)
    started = time.perf_counter()
    stage = "connect"
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS) as server:
            stage = "starttls"
            server.starttls()
            stage = "login"
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            stage = "send"
            server.sendmail(config.EMAIL_FROM, [to_addr], msg.as_string())
        log_email("sent", {**ctx, "duration_ms": round((time.perf_counter() - started) * 1000, 1)})
        get_session().log_activity("ok", f"Email sent to {to_addr} — {subject}")
        return {"sent": True, "dry_run": False, "to": to_addr, "subject": subject}
    except Exception as exc:  # pragma: no cover - network failure path
        code = getattr(exc, "smtp_code", None)
        raw = getattr(exc, "smtp_error", b"")
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw or exc)
        name = type(exc).__name__
        log_email("failed", {
            **ctx, "stage": stage, "error_type": name, "smtp_code": code,
            "smtp_error": text[:300] or str(exc)[:300],
            "hint": _failure_hint(code, text or str(exc), stage, name),
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }, level=logging.ERROR)
        get_session().log_activity("conflict", f"Email send failed at {stage}: {exc}")
        return {"sent": False, "dry_run": False, "error": str(exc), "stage": stage, "to": to_addr}


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
    log_email("tokens_issued", {"kind": "approval_request", "employee_time_id": employee_time_id,
                                "ttl_hours": TOKEN_TTL.total_seconds() / 3600})
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
    result = _send(manager_email, f"Leave approval needed — {req['start_date']} to {req['end_date']}", html,
                   kind="approval_request", employee_time_id=employee_time_id)
    result.update(
        {"manager_email": manager_email, "approve_url": approve_url, "reject_url": reject_url}
    )
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
    return _send(employee.get("email", ""), f"Leave approved — {employee_time_id}", html,
                 kind="confirmation", employee_time_id=employee_time_id)


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
    return _send(employee.get("email", ""), f"Leave not approved — {employee_time_id}", html,
                 kind="rejection", employee_time_id=employee_time_id)
