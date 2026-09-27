"""The interview state machine.

Transport-agnostic on purpose: it knows nothing about audio, LiveKit, or stdin.
Both adapters drive this same object, which is what makes the free text dev
loop and the phase 8 eval harness possible. If this module ever imports
livekit, the design has broken.

`answer` is an async generator. The caller gets words as they arrive and can
start speaking the first sentence before the last one exists - which is the
only way the 800 ms budget is reachable.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from greenroom.latency import LatencyBook, percentile
from greenroom.llm.client import LLM
from greenroom.stages import definitions as d


@dataclass
class Turn:
    speaker: str  # "interviewer" | "candidate"
    text: str
    t_start: float
    t_end: float
    ttft_ms: int | None = None  # interviewer: to the first word out of the model
    think_ms: int | None = None  # interviewer: to the whole reply assembled

    @property
    def duration_s(self) -> float:
        return self.t_end - self.t_start


@dataclass
class StageMachine:
    llm: LLM
    questions: list[str] = field(default_factory=lambda: list(d.QUESTIONS))
    transcript: list[Turn] = field(default_factory=list)
    latency: LatencyBook = field(default_factory=LatencyBook)
    done: bool = False
    _asked: int = 0
    _t0: float = field(default_factory=time.monotonic)

    def open(self) -> str:
        """The interviewer's first line. No model call - it's fixed."""
        self._record("interviewer", d.OPENING, self.elapsed(), self.elapsed())
        return d.OPENING

    async def answer(self, text: str, *, t_start: float | None = None) -> AsyncIterator[str]:
        """Candidate said `text`. Yields the interviewer's reply as it arrives.

        Read `done` after the stream is exhausted. The acknowledgement streams
        from the model; the question that follows it is appended locally, so it
        costs nothing and arrives the instant the model stops.
        """
        end = self.elapsed()
        self._record("candidate", text, t_start if t_start is not None else end, end)

        started = time.monotonic()
        ttft_ms: int | None = None
        parts: list[str] = []

        async for piece in self.llm.stream(d.SYSTEM, text, max_tokens=60):
            if ttft_ms is None:
                ttft_ms = int((time.monotonic() - started) * 1000)
            parts.append(piece)
            yield piece

        if self._asked < len(self.questions):
            tail = " " + self.questions[self._asked]
            self._asked += 1
        else:
            tail = " " + d.CLOSING
            self.done = True
        yield tail
        parts.append(tail)

        think_ms = int((time.monotonic() - started) * 1000)
        if ttft_ms is not None:
            self.latency.record("llm_ttft", ttft_ms)
        self.latency.record("llm_full", think_ms)
        t = self.elapsed()
        self._record(
            "interviewer", "".join(parts).strip(), t, t, ttft_ms=ttft_ms, think_ms=think_ms
        )

    # ---- transcript ----

    def elapsed(self) -> float:
        """Seconds since the interview opened."""
        return time.monotonic() - self._t0

    def _record(self, speaker: str, text: str, t_start: float, t_end: float, **kw: int) -> None:
        self.transcript.append(Turn(speaker, text, t_start, t_end, **kw))

    def latencies(self) -> dict[str, int]:
        """Per-layer numbers the phase 2 gate is measured against."""
        ttft = [t.ttft_ms for t in self.transcript if t.ttft_ms is not None]
        full = [t.think_ms for t in self.transcript if t.think_ms is not None]
        return {
            "turns": len(ttft),
            "llm_ttft_p50": percentile(ttft, 50),
            "llm_ttft_p95": percentile(ttft, 95),
            "llm_full_p50": percentile(full, 50),
            "llm_full_p95": percentile(full, 95),
        }

    def format_transcript(self) -> str:
        def clock(s: float) -> str:
            return f"{int(s) // 60:02d}:{s % 60:04.1f}"

        lines = ["", "── transcript ──"]
        for t in self.transcript:
            timing = f"  (ttft {t.ttft_ms} ms, full {t.think_ms} ms)" if t.ttft_ms else ""
            when = f"[{clock(t.t_start)} → {clock(t.t_end)}]"
            lines.append(f"{when} {t.speaker:<11} {t.text}{timing}")

        m = self.latencies()
        if m["turns"]:
            lines += [
                "",
                f"{m['turns']} interviewer turns  |  "
                f"LLM first token p50 {m['llm_ttft_p50']} ms / p95 {m['llm_ttft_p95']} ms  |  "
                f"full reply p50 {m['llm_full_p50']} ms / p95 {m['llm_full_p95']} ms",
            ]
        return "\n".join(lines) + "\n" + self.latency.format()
