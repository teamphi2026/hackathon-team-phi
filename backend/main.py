"""FastAPI application entry point.

Wires the orchestrator agent, the approval token callback, session-state
polling for the manager UI, the Agent Activity SSE stream, and a demo reset.

Run with:
    uvicorn backend.main:app --reload
"""
from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import agent, email_service
from .state import get_session
from .tools import actions

app = FastAPI(title="Project-Aware Leave Planning Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    """Main chat endpoint — delegates to the orchestrator agent."""
    return agent.handle_message(req.message)


@app.post("/api/approval/{token}")
def approval(token: str, action: str = "approve") -> dict:
    """Manager Approve/Reject token callback.

    Applies the decision via the state machine, then emails the employee.
    """
    result = actions.handle_approval_token(token, action)
    if result.get("success"):
        eid = result["employee_time_id"]
        if result["action"] == "approve":
            email_service.send_confirmation_email(eid)
        else:
            email_service.send_rejection_email(eid, reason="Rejected by manager")
    return result


class UIApproval(BaseModel):
    action: str


@app.post("/api/ui-approval")
def ui_approval(req: UIApproval) -> dict:
    """Manager decision made in the UI card (not via an email token).

    Acts on the session's current pending request. Mirrors the token path:
    applies the state transition then emails the employee.
    """
    s = get_session()
    if not s.reference_id:
        return {"success": False, "message": "No pending request to decide on."}
    result = actions.handle_ui_decision(s.reference_id, req.action)
    if result.get("success"):
        eid = result["employee_time_id"]
        if result["action"] == "approve":
            email_service.send_confirmation_email(eid)
        else:
            email_service.send_rejection_email(eid, reason="Rejected by manager")
    return result


@app.get("/api/session-state")
def session_state() -> dict:
    """Snapshot of workflow state for the manager approval UI card."""
    s = get_session()
    return {
        "user_id": s.session_user_id,
        "employee_confirmed": s.employee_confirmed,
        "employee_time_id": s.employee_time_id,
        "approval_status": s.approval_status,
        "reference_id": s.reference_id,
        "activity": s.activity,
    }


@app.post("/api/reset")
def reset() -> dict[str, str]:
    get_session().reset()
    return {"status": "reset"}


@app.get("/api/activity")
async def activity_stream() -> StreamingResponse:
    """SSE stream of Agent Activity events for the right-hand panel."""

    async def event_gen():
        session = get_session()
        last = 0
        for _ in range(1200):  # ~10 min at 0.5s cadence
            events = session.activity[last:]
            for ev in events:
                yield f"data: {json.dumps(ev)}\n\n"
            last = len(session.activity)
            await asyncio.sleep(0.5)

    return StreamingResponse(event_gen(), media_type="text/event-stream")
