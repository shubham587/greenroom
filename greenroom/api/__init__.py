"""The HTTP surface. Stateless, and never calls a model inside a request handler."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from livekit import api
from sqlalchemy import select

from greenroom.config import settings
from greenroom.db.models import Session, Turn
from greenroom.db.session import db

app = FastAPI(title="Greenroom")

# Resolved from the package, not the working directory.
_DEV_CLIENT = Path(__file__).resolve().parents[2] / "scripts" / "devclient.html"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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


@app.get("/dev/token")
def dev_token(room: str = "greenroom", identity: str = "candidate") -> dict[str, str]:
    """Mint a LiveKit join token for the throwaway dev client.

    Dev only. Phase 9 replaces this with a real per-session endpoint that checks
    the session exists and belongs to the caller.
    """
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .to_jwt()
    )
    return {"token": token, "url": settings.livekit_url, "room": room}


@app.get("/dev")
def dev_client() -> FileResponse:
    """Throwaway browser client for phases 1-8. The real app arrives in phase 9."""
    return FileResponse(_DEV_CLIENT)
