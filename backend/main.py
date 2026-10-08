"""FastAPI application entry point.

Task 1 / Phase 0 skeleton: dummy routes so the app runs end-to-end before
the tool layer, orchestrator, and email service are implemented. Later tasks
replace the dummy bodies with real behaviour.

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

from .state import get_session

app = FastAPI(title="Project-Aware Leave Planning Agent")

# Permit the static UI / Vercel frontend to call the API during the demo.
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
def chat(req: ChatRequest) -> dict[str, str]:
    """Dummy chat endpoint — replaced by the orchestrator in a later task."""
    session = get_session()
    session.log_activity("waiting", f"Received: {req.message!r}")
    return {
        "reply": (
            "Backend skeleton is live. The orchestrator agent is not wired up "
            "yet — this is a placeholder response."
        ),
        "user_id": session.session_user_id,
    }


@app.post("/api/approval/{token}")
def approval(token: str, action: str = "approve") -> dict[str, str]:
    """Stub for the manager Approve/Reject token callback."""
    return {
        "status": "stub",
        "token": token,
        "action": action,
        "message": "Approval handler not implemented yet.",
    }


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
        # Emit a short-lived stream for the demo; the UI reconnects as needed.
        for _ in range(600):  # ~5 min at 0.5s cadence
            events = session.activity[last:]
            for ev in events:
                yield f"data: {json.dumps(ev)}\n\n"
            last = len(session.activity)
            await asyncio.sleep(0.5)

    return StreamingResponse(event_gen(), media_type="text/event-stream")
