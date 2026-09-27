"""Measure each layer of a turn against its budget, ten times.

The phase 2 gate needs p50 and p95 per layer, not a total, and not one
sample. This talks to the real APIs - cassettes are bypassed on purpose,
since the point is the latency they exist to avoid paying.

    uv run python scripts/bench.py [runs]

It measures the three provider legs. LiveKit transport and endpointing sit on
top of these in a real session, so treat the total here as a floor rather than
the number a candidate experiences.
"""

from __future__ import annotations

import asyncio
import io
import sys
import time

from openai import AsyncOpenAI

from greenroom.config import settings
from greenroom.latency import BUDGET_MS, LatencyBook
from greenroom.stages import definitions as d

client = AsyncOpenAI(api_key=settings.openai_api_key)

ANSWER = "I rebuilt our order events pipeline on Kafka and owned the consumer side."
REPLY = "You rebuilt the order events pipeline on Kafka. What part were you most responsible for?"


async def time_llm() -> float:
    extra = (
        {"reasoning_effort": settings.llm_reasoning_effort} if settings.llm_reasoning_effort else {}
    )
    t0 = time.monotonic()
    stream = await client.chat.completions.create(
        model=settings.model_conversation,
        messages=[{"role": "system", "content": d.SYSTEM}, {"role": "user", "content": ANSWER}],
        max_completion_tokens=60,
        stream=True,
        **extra,
    )
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            return (time.monotonic() - t0) * 1000
    return (time.monotonic() - t0) * 1000


async def time_tts() -> float:
    """Time to the first audio chunk, which is what a listener perceives.

    pcm, not wav: a wav stream makes the client wait on a container header and
    the request never yields an early chunk.
    """
    t0 = time.monotonic()
    async with client.audio.speech.with_streaming_response.create(
        model=settings.tts_model, voice=settings.tts_voice, input=REPLY, response_format="pcm"
    ) as resp:
        async for _ in resp.iter_bytes(4096):
            return (time.monotonic() - t0) * 1000
    return (time.monotonic() - t0) * 1000


async def sample_clip() -> bytes:
    """One spoken clip for the speech-to-text leg to transcribe."""
    audio = await client.audio.speech.create(
        model=settings.tts_model, voice=settings.tts_voice, input=ANSWER, response_format="wav"
    )
    return audio.content


async def time_stt(audio: bytes) -> float:
    f = io.BytesIO(audio)
    f.name = "turn.wav"
    t0 = time.monotonic()
    await client.audio.transcriptions.create(model=settings.stt_model, file=f)
    return (time.monotonic() - t0) * 1000


async def main(runs: int) -> None:
    print(
        f"llm={settings.model_conversation}  stt={settings.stt_model}  "
        f"tts={settings.tts_model}  runs={runs}\n"
    )
    book = LatencyBook()

    audio = await sample_clip()
    await time_tts()  # discard: first call pays connection setup

    for i in range(runs):
        book.record("llm_ttft", await time_llm())
        book.record("tts_ttfb", await time_tts())
        book.record("stt", await time_stt(audio))
        print(f"  run {i + 1}/{runs}", flush=True)

    print()
    print(book.format())

    s = book.summary()
    serial_p50 = sum(s[k]["p50"] for k in ("stt", "llm_ttft", "tts_ttfb") if k in s)
    serial_p95 = sum(s[k]["p95"] for k in ("stt", "llm_ttft", "tts_ttfb") if k in s)
    print(f"\nserial turn total   p50 {serial_p50} ms   p95 {serial_p95} ms")
    print("gate                p50 3500 ms   p95 4500 ms")
    ok = serial_p50 <= 3500 and serial_p95 <= 4500
    print("\n" + ("GATE MET" if ok else "GATE NOT MET"))

    worst = max(s, key=lambda k: s[k]["p50"] / max(BUDGET_MS.get(k, (0, 1))[1], 1))
    print(f"largest gap to budget: {worst}")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 10))
