"""Voice driver for the stage machine: LiveKit in, LiveKit out.

Note what is NOT here: the LLM. AgentSession is given stt, vad and tts only,
and the interviewer's words come from our own StageMachine via session.say().
Keeping the conversation call in our code is what makes it cassette-able,
swappable per stage, and identical to what the text adapter runs.

Turn handling is LiveKit's job, not ours. We answer on `on_user_turn_completed`
- the point at which LiveKit has decided the candidate is finished - and never
on raw transcripts, which arrive mid-turn while the candidate is still talking.
The hook itself only queues the text: speaking from inside it blocks the very
turn machinery that called it.
"""

from __future__ import annotations

import asyncio
import logging
import os

from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli, llm
from livekit.plugins import silero

from greenroom.adapters.providers import build_stt, build_tts
from greenroom.config import settings
from greenroom.db.models import Session
from greenroom.db.session import db
from greenroom.events import session_completed, turn_completed
from greenroom.llm.client import get_llm
from greenroom.schemas.intake import CoverageMap
from greenroom.stages.machine import StageMachine, is_backchannel
from greenroom.tracing import setup as setup_tracing

log = logging.getLogger("greenroom.agent")

server = AgentServer()


class Interviewer(Agent):
    """Hands each completed candidate turn to the queue and returns immediately."""

    def __init__(self, turns: asyncio.Queue[str]) -> None:
        super().__init__(instructions="")
        self._turns = turns

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ) -> None:
        text = (new_message.text_content or "").strip()
        if not text:
            return
        if is_backchannel(text):
            log.info("backchannel, not an answer: %s", text)
            return
        log.info("heard: %s", text)
        self._turns.put_nowait(text)


def _machine_for(room_name: str) -> StageMachine:
    """Build the interview for the session this room belongs to.

    Falls back to the fixed script when the room is not a session room, which
    is what the throwaway dev client at /dev still uses.
    """
    if not room_name.startswith("session_"):
        log.info("room %s is not a session room - running the fixed script", room_name)
        return StageMachine(llm=get_llm(), on_turn=turn_completed)

    session_id = room_name.removeprefix("session_")
    with db() as s:
        session = s.get(Session, session_id)
        raw = session.coverage_map if session else None

    if not raw:
        log.warning("session %s has no coverage map - falling back", session_id)
        return StageMachine(llm=get_llm(), on_turn=turn_completed, session_id=session_id)

    coverage = CoverageMap.model_validate(raw)
    machine = StageMachine(
        llm=get_llm(),
        on_turn=turn_completed,
        coverage=coverage,
        session_id=session_id,
        stage="deep_dive",
    )
    unprobed = coverage.unprobed()
    machine.topic = unprobed[0].name if unprobed else ""
    log.info(
        "session %s: %d topics, opening on %s", session_id, len(coverage.topics), machine.topic
    )
    return machine


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    setup_tracing()
    await ctx.connect()

    # The room is named after the session, which is how the agent knows whose
    # interview it has been handed. Without it every candidate would get the
    # same generic script regardless of what they uploaded.
    machine = _machine_for(ctx.room.name)
    turns: asyncio.Queue[str] = asyncio.Queue()

    session = AgentSession(
        stt=build_stt(),
        tts=build_tts(),
        vad=silero.VAD.load(),
        turn_handling={
            # Batch speech-to-text takes ~1.1 s, slower than the default
            # endpointing window, so the transcript lands after the turn is
            # committed. Drops to ~0.3 s if we move to streaming transcription.
            "endpointing": {"min_delay": 1.5},
            # Barge-in: the candidate talks over the interviewer, it stops.
            "interruption": {"enabled": True},
        },
    )
    log.info(
        "providers stt=%s (%s) tts=%s (%s)",
        settings.stt_provider,
        settings.stt_model,
        settings.tts_provider,
        settings.tts_model,
    )

    @session.on("metrics_collected")
    def _on_metrics(ev) -> None:  # noqa: ANN001 - livekit passes its own event type
        # Speech legs are measured by LiveKit; the LLM leg by the machine.
        machine.latency.on_livekit_metrics(getattr(ev, "metrics", ev))

    async def conversation() -> None:
        """One consumer, so replies are serialised and never overlap."""
        turn_opened = machine.elapsed()
        while True:
            text = await turns.get()
            said_at, turn_opened = turn_opened, machine.elapsed()
            try:
                # say() takes the async iterator directly, so text-to-speech
                # starts on the first sentence rather than waiting for the
                # model to finish.
                handle = session.say(machine.answer(text, t_start=said_at))
                await handle
            except Exception:
                log.exception("failed to answer; saying so rather than going silent")
                await session.say("Sorry, give me one moment.")
                continue

            if handle.interrupted and machine.rewind_question():
                log.info("cut off mid-question - will ask it again")
                continue

            if machine.done:
                log.info(machine.format_transcript())
                await session_completed(machine.session_id)
                ctx.shutdown(reason="interview complete")
                return

    await session.start(agent=Interviewer(turns), room=ctx.room)
    log.info("session %s", machine.session_id)
    await session.say(machine.open())

    await conversation()


def main() -> None:
    if not settings.openai_api_key:
        raise SystemExit(
            "OPENAI_API_KEY is not set. The voice adapter needs it for speech-to-text "
            "and text-to-speech. Use `make text` to run the interview without it."
        )

    # LiveKit's CLI and the OpenAI plugin read the OS environment directly, not
    # our settings object, so .env values have to be exported for them.
    for name, value in (
        ("LIVEKIT_URL", settings.livekit_url),
        ("LIVEKIT_API_KEY", settings.livekit_api_key),
        ("LIVEKIT_API_SECRET", settings.livekit_api_secret),
        ("OPENAI_API_KEY", settings.openai_api_key),
    ):
        os.environ.setdefault(name, value)

    # run_app owns the event loop and parses the dev/start subcommands.
    cli.run_app(server)
