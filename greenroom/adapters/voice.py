"""Voice driver for the stage machine: LiveKit in, LiveKit out.

Note what is NOT here: the LLM. AgentSession is given stt, vad and tts only,
and the interviewer's words come from our own StageMachine via session.say().
Keeping the conversation call in our code is what makes it cassette-able,
swappable per stage, and identical to what the text adapter runs.
"""

from __future__ import annotations

import logging

from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli
from livekit.plugins import openai, silero

from greenroom.config import settings
from greenroom.llm.client import get_llm
from greenroom.stages.machine import StageMachine

log = logging.getLogger("greenroom.agent")

server = AgentServer()


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    machine = StageMachine(llm=get_llm())

    session = AgentSession(
        stt=openai.STT(),
        tts=openai.TTS(),
        vad=silero.VAD.load(),
    )

    turn_opened = 0.0

    @session.on("user_input_transcribed")
    def _on_transcript(ev) -> None:  # noqa: ANN001 - livekit passes its own event type
        nonlocal turn_opened
        if not ev.is_final or not ev.transcript.strip():
            return
        said_at, turn_opened = turn_opened, machine.elapsed()
        ctx.create_task(_respond(ev.transcript.strip(), said_at))

    async def _respond(text: str, said_at: float) -> None:
        reply = await machine.answer(text, t_start=said_at)
        await session.say(reply.text)
        if reply.done:
            log.info(machine.format_transcript())
            ctx.shutdown(reason="interview complete")

    await session.start(agent=Agent(instructions=""), room=ctx.room)

    turn_opened = machine.elapsed()
    await session.say(machine.open().text)


def main() -> None:
    if not settings.openai_api_key:
        raise SystemExit(
            "OPENAI_API_KEY is not set. The voice adapter needs it for speech-to-text "
            "and text-to-speech. Use `make text` to run the interview without it."
        )
    # run_app owns the event loop and parses the dev/start subcommands.
    cli.run_app(server)
