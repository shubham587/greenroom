"""Voice driver for the stage machine: LiveKit in, LiveKit out.

Note what is NOT here: the LLM. AgentSession is given stt, vad and tts only,
and the interviewer's words come from our own StageMachine via session.say().
Keeping the conversation call in our code is what makes it cassette-able,
swappable per stage, and identical to what the text adapter runs.
"""

from __future__ import annotations

import logging
import os

from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli
from livekit.plugins import silero

from greenroom.adapters.providers import build_stt, build_tts
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
        stt=build_stt(),
        tts=build_tts(),
        vad=silero.VAD.load(),
    )
    log.info("providers stt=%s tts=%s", settings.stt_provider, settings.tts_provider)

    turn_opened = 0.0

    @session.on("metrics_collected")
    def _on_metrics(ev) -> None:  # noqa: ANN001 - livekit passes its own event type
        # Speech legs are measured by LiveKit; the LLM leg by the machine.
        machine.latency.on_livekit_metrics(getattr(ev, "metrics", ev))

    @session.on("user_input_transcribed")
    def _on_transcript(ev) -> None:  # noqa: ANN001 - livekit passes its own event type
        nonlocal turn_opened
        if not ev.is_final or not ev.transcript.strip():
            return
        said_at, turn_opened = turn_opened, machine.elapsed()
        ctx.create_task(_respond(ev.transcript.strip(), said_at))

    async def _respond(text: str, said_at: float) -> None:
        # say() takes the async iterator directly, so text-to-speech starts on
        # the first sentence instead of waiting for the model to finish.
        # allow_interruptions is the barge-in: the candidate talks over the
        # interviewer and the interviewer stops, as a person would.
        await session.say(machine.answer(text, t_start=said_at), allow_interruptions=True)
        if machine.done:
            log.info(machine.format_transcript())
            ctx.shutdown(reason="interview complete")

    await session.start(agent=Agent(instructions=""), room=ctx.room)

    turn_opened = machine.elapsed()
    await session.say(machine.open())


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
