"""Text driver for the stage machine: stdin in, stdout out.

The same machine the voice adapter drives, with no speech-to-text or
text-to-speech cost. This is the loop to iterate interview logic in - a full
run costs a few cents instead of a few dollars, and it is what the phase 8
eval harness replays through.

Words are printed as they stream, so the perceived latency here is the same
thing the voice adapter measures: time to the first word, not the last.
"""

from __future__ import annotations

import asyncio
import sys

from greenroom.llm.client import get_llm
from greenroom.stages.machine import StageMachine
from greenroom.tracing import setup as setup_tracing


async def run() -> None:
    setup_tracing()
    machine = StageMachine(llm=get_llm())

    print(f"\ninterviewer  {machine.open()}\n")

    while True:
        turn_opened = machine.elapsed()
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:  # EOF
            break
        answer = line.strip()
        if not answer:
            continue
        if answer in {"/quit", "/q"}:
            break

        print("\ninterviewer  ", end="", flush=True)
        async for piece in machine.answer(answer, t_start=turn_opened):
            print(piece, end="", flush=True)
        print("\n")

        if machine.done:
            break

    print(machine.format_transcript())


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
