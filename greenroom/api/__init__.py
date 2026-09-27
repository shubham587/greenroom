"""The HTTP surface. Stateless, and never calls a model inside a request handler."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from livekit import api

from greenroom.config import settings

app = FastAPI(title="Greenroom")

# Resolved from the package, not the working directory.
_DEV_CLIENT = Path(__file__).resolve().parents[2] / "scripts" / "devclient.html"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
