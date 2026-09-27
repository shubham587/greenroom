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
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

from greenroom.latency import LatencyBook, percentile
from greenroom.llm.client import LLM
from greenroom.stages import definitions as d
from greenroom.tracing import current_session

# ponytail: flat word set, good enough to stop "yes" ending an interview.
# If it starts eating real one-word answers, score the utterance instead.
BACKCHANNEL = {
    "yes",
    "yeah",
    "yep",
    "yup",
    "no",
    "nope",
    "ok",
    "okay",
    "right",
    "sure",
    "correct",
    "exactly",
    "mm",
    "mhm",
    "mhmm",
    "huh",
    "got",
    "see",
    "understood",
    "true",
}


FILLER = {"that", "is", "was", "a", "so", "and", "i", "it"}


def is_backchannel(text: str) -> bool:
    """Agreement noises made while the interviewer talks are not answers.

    A real candidate says "yes, that's right" over the top of a question and
    means nothing by it; counting that as a turn burns a question they never
    got to hear.
    """
    words = [w.strip(".,!?;:'\"") for w in text.lower().split()]
    words = [w for w in words if w]
    if not words or len(words) > 5:
        return False
    # every word is either an agreement token or connective tissue between
    # them, and at least one is an actual agreement
    meaningful = [w for w in words if w not in FILLER]
    return bool(meaningful) and all(w in BACKCHANNEL for w in meaningful)


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
    stage: str = "intro"
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    # where completed turns go. None keeps the machine pure, which is what
    # the tests and the eval harness want.
    on_turn: Callable[[dict], Awaitable[None]] | None = None
    _asked: int = 0
    _last_tail_was_question: bool = False
    _t0: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        # every model call made while this machine is live is labelled with
        # its interview, so the turns group instead of arriving as orphans
        current_session.set(self.session_id)

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
            self._last_tail_was_question = True
        else:
            tail = " " + d.CLOSING
            self.done = True
            self._last_tail_was_question = False
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
        await self._emit(self.transcript[-2])  # what the candidate said
        await self._emit(self.transcript[-1])  # and what the interviewer said back

    def rewind_question(self) -> bool:
        """The last question was cut off before the candidate heard it.

        Barge-in truncates the interviewer mid-sentence, but the machine has
        already counted the question as asked - so the candidate is answering
        something they never heard. Put it back, and it gets asked again.
        """
        if not self._last_tail_was_question or self._asked == 0:
            return False
        self._asked -= 1
        self._last_tail_was_question = False
        return True

    # ---- transcript ----

    def elapsed(self) -> float:
        """Seconds since the interview opened."""
        return time.monotonic() - self._t0

    def _record(self, speaker: str, text: str, t_start: float, t_end: float, **kw: int) -> None:
        self.transcript.append(Turn(speaker, text, t_start, t_end, **kw))

    async def _emit(self, turn: Turn) -> None:
        if self.on_turn is None:
            return
        await self.on_turn(
            {
                "session_id": self.session_id,
                "stage": self.stage,
                "speaker": turn.speaker,
                "text": turn.text,
                "t_start": turn.t_start,
                "t_end": turn.t_end,
                "ttft_ms": turn.ttft_ms,
                "think_ms": turn.think_ms,
            }
        )

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
