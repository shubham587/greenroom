"""The interview state machine.

Transport-agnostic on purpose: it knows nothing about audio, LiveKit, or stdin.
Both adapters drive this same object, which is what makes the free text dev
loop and the phase 8 eval harness possible. If this module ever imports
livekit, the design has broken.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from greenroom.llm.client import LLM
from greenroom.stages import definitions as d


@dataclass
class Turn:
    speaker: str  # "interviewer" | "candidate"
    text: str
    t_start: float
    t_end: float
    think_ms: int | None = None  # interviewer turns: time spent deciding what to say

    @property
    def duration_s(self) -> float:
        return self.t_end - self.t_start


@dataclass
class Reply:
    text: str
    done: bool = False


@dataclass
class StageMachine:
    llm: LLM
    questions: list[str] = field(default_factory=lambda: list(d.QUESTIONS))
    transcript: list[Turn] = field(default_factory=list)
    _asked: int = 0
    _t0: float = field(default_factory=time.monotonic)

    def open(self) -> Reply:
        """The interviewer's first line. No model call - it's fixed."""
        self._record("interviewer", d.OPENING, self.elapsed(), self.elapsed())
        return Reply(d.OPENING)

    async def answer(self, text: str, *, t_start: float | None = None) -> Reply:
        """Candidate said `text`. Returns what the interviewer says back."""
        end = self.elapsed()
        self._record("candidate", text, t_start if t_start is not None else end, end)

        think_start = time.monotonic()
        ack = await self.llm.complete(d.SYSTEM, text, max_tokens=60)

        if self._asked < len(self.questions):
            reply_text = f"{ack} {self.questions[self._asked]}".strip()
            self._asked += 1
            done = False
        else:
            reply_text = f"{ack} {d.CLOSING}".strip()
            done = True

        think_ms = int((time.monotonic() - think_start) * 1000)
        t = self.elapsed()
        self._record("interviewer", reply_text, t, t, think_ms=think_ms)
        return Reply(reply_text, done=done)

    # ---- transcript ----

    def elapsed(self) -> float:
        """Seconds since the interview opened."""
        return time.monotonic() - self._t0

    def _record(self, speaker: str, text: str, t_start: float, t_end: float, **kw: int) -> None:
        self.transcript.append(Turn(speaker, text, t_start, t_end, **kw))

    def format_transcript(self) -> str:
        def clock(s: float) -> str:
            return f"{int(s) // 60:02d}:{s % 60:04.1f}"

        lines = ["", "── transcript ──"]
        for t in self.transcript:
            think = f"  ({t.think_ms} ms)" if t.think_ms is not None else ""
            lines.append(f"[{clock(t.t_start)} → {clock(t.t_end)}] {t.speaker:<11} {t.text}{think}")

        thinks = [t.think_ms for t in self.transcript if t.think_ms is not None]
        if thinks:
            lines += [
                "",
                f"interviewer turns: {len(thinks)}  "
                f"think time min/median/max: {min(thinks)} / "
                f"{sorted(thinks)[len(thinks) // 2]} / {max(thinks)} ms",
            ]
        return "\n".join(lines)
