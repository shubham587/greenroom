"""The HTTP surface. Stateless, and never calls a model inside a request handler."""

from __future__ import annotations

import asyncio
import contextlib
import json

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from livekit import api
from sqlalchemy import select

from greenroom.config import settings
from greenroom.db.models import Report, Session, Turn
from greenroom.db.session import db
from greenroom.intake import extract_pdf
from greenroom.worker.presession import prepare_session

app = FastAPI(title="Greenroom")

# the web client runs on another origin in development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/sessions", status_code=201)
async def create_session(
    resume: UploadFile = File(...),  # noqa: B008 - FastAPI's dependency form
    jd: str = Form(...),
) -> dict[str, str]:
    """Upload a resume and a job description, and start the intake.

    Returns immediately with an id to watch. No model is called in this
    handler: extraction is deterministic, and everything that needs a model
    happens on the queue where nobody is waiting for it.
    """
    data = await resume.read()
    if not data:
        raise HTTPException(400, "the resume file is empty")

    name = (resume.filename or "").lower()
    try:
        text = extract_pdf(data) if name.endswith(".pdf") else data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "could not read that file as a PDF or as text") from None

    if not text.strip():
        raise HTTPException(400, "no text found in that resume - is it a scanned image?")
    if not jd.strip():
        raise HTTPException(400, "the job description is empty")

    with db() as s:
        session = Session(state="created")
        s.add(session)
        s.flush()
        session_id = session.id

    prepare_session.delay(session_id, text, jd)
    return {"session_id": session_id}


@app.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    with db() as s:
        session = s.get(Session, session_id)
        if session is None:
            raise HTTPException(404, "no such session")
        turns = s.scalars(
            select(Turn).where(Turn.session_id == session_id).order_by(Turn.t_start)
        ).all()
        return {
            "id": session.id,
            "state": session.state,
            "stage": session.stage,
            "created_at": session.created_at.isoformat(),
            "turns": [
                {
                    "speaker": t.speaker,
                    "text": t.text,
                    "t_start": round(t.t_start, 2),
                    "ttft_ms": t.ttft_ms,
                }
                for t in turns
            ],
        }


@app.websocket("/ws/sessions/{session_id}")
async def session_state(ws: WebSocket, session_id: str) -> None:
    """Push session state to the browser.

    Polling the row is deliberate for now: the only writer is a Celery worker
    in another process, and a poll is a great deal less machinery than a
    pub/sub fan-out for a payload that changes a few times a minute. Phase 6
    swaps it when the coverage map needs pushing live.
    """
    await ws.accept()
    last: str | None = None
    try:
        while True:
            with db() as s:
                session = s.get(Session, session_id)
                payload = (
                    {"state": "unknown", "turns": 0}
                    if session is None
                    else {
                        "state": session.state,
                        "stage": session.stage,
                        "turns": len(session.turns),
                        # the coverage map filling in is the thing worth watching
                        "coverage": [
                            {"name": t["name"], "status": t["status"], "priority": t["priority"]}
                            for t in (session.coverage_map or {}).get("topics", [])
                        ],
                    }
                )
            current = json.dumps(payload, sort_keys=True)
            if current != last:
                await ws.send_text(current)
                last = current
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
    except Exception:
        with contextlib.suppress(Exception):
            await ws.close()


@app.get("/sessions/{session_id}/token")
def session_token(session_id: str) -> dict[str, str]:
    """A LiveKit token scoped to one session's room.

    Checks the session exists and is ready, which the dev endpoint never did.
    """
    with db() as s:
        session = s.get(Session, session_id)
        if session is None:
            raise HTTPException(404, "no such session")
        if session.state not in {"ready", "live"}:
            raise HTTPException(409, f"session is {session.state}, not ready")

    room = f"session_{session_id}"
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity("candidate")
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .to_jwt()
    )
    return {"token": token, "url": settings.livekit_url, "room": room}


@app.get("/sessions/{session_id}/report")
def get_report(session_id: str) -> dict:
    with db() as s:
        report = s.query(Report).filter_by(session_id=session_id).one_or_none()
        if report is None:
            raise HTTPException(404, "no report yet")
        return {
            "narrative": report.narrative,
            "dimension_scores": report.dimension_scores,
            "delivery": report.delivery,
            "coverage": (report.coverage or {}).get("topics", []),
        }
