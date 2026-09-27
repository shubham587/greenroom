"""How the agent hands work to the slow loop.

The agent must not block on a broker round trip inside a turn, and it must not
crash the interview if Redis is down - a dropped scoring task costs a line in
the report, a raised exception costs the conversation. So: queued off-thread,
failures logged and swallowed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)


def _send(name: str, *args: Any) -> None:
    from greenroom.worker.app import app

    app.send_task(name, args=args)


async def emit(name: str, *args: Any) -> None:
    """Queue a task without making the conversation wait for it."""
    try:
        await asyncio.to_thread(_send, name, *args)
    except Exception as exc:  # broker down, misconfigured, anything
        log.warning("could not queue %s: %s", name, exc)


async def turn_completed(payload: dict) -> None:
    await emit("greenroom.worker.record_turn", payload)


async def session_completed(session_id: str, state: str = "completed") -> None:
    await emit("greenroom.worker.close_session", session_id, state)
