"""Text driver for the stage machine: stdin in, stdout out.

The same machine the voice adapter drives, with no speech-to-text or
text-to-speech cost. This is the loop to iterate interview logic in - a full
run costs a few cents instead of a few dollars, and it is what the phase 8
eval harness replays through.
"""

from __future__ import annotations

import asyncio
import sys

from greenroom.llm.client import get_llm
from greenroom.stages.machine import StageMachine


async def run() -> None:
    machine = StageMachine(llm=get_llm())

    print(f"\ninterviewer  {machine.open().text}\n")

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

        reply = await machine.answer(answer, t_start=turn_opened)
        print(f"\ninterviewer  {reply.text}\n")
        if reply.done:
            break

    print(machine.format_transcript())


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
