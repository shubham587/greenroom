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

from greenroom import review
from greenroom.latency import LatencyBook, percentile
from greenroom.llm.client import LLM
from greenroom.routing import apply as apply_route
from greenroom.routing import classify
from greenroom.schemas.intake import CoverageMap
from greenroom.schemas.routing import Decision
from greenroom.stages import context as ctx
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
    # None keeps phase 1 behaviour: one stage, the fixed question script.
    stages: list[d.Stage] | None = None
    static_context: str = ""
    summary: str = ""
    _stage_idx: int = 0
    _stage_started: float = 0.0
    _stage_turns: int = 0
    _nudged: bool = False
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    # where completed turns go. None keeps the machine pure, which is what
    # the tests and the eval harness want.
    on_turn: Callable[[dict], Awaitable[None]] | None = None
    # with a map, the interviewer follows the candidate; without one it walks
    # the fixed script, which is what the phase 1 tests still exercise.
    coverage: CoverageMap | None = None
    topic: str = ""
    decisions: list[Decision] = field(default_factory=list)
    # ---- the coding round ----
    problem_statement: str = ""
    problem_probes: list[str] = field(default_factory=list)
    language: str = "python"
    # what they SAID they would do, captured while the editor was locked.
    # Without this the review has nothing to compare the code against.
    approach_text: str = ""
    code: str = ""
    snapshots: list[dict] = field(default_factory=list)
    test_results: dict | None = None
    _reviewed: bool = False
    _asked: int = 0
    _last_tail_was_question: bool = False
    _t0: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        # every model call made while this machine is live is labelled with
        # its interview, so the turns group instead of arriving as orphans
        current_session.set(self.session_id)

    def open(self) -> str:
        """The interviewer's first line. No model call - it's fixed."""
        line = self.current_stage.opening if self.stages else d.OPENING
        self._record("interviewer", line, self.elapsed(), self.elapsed())
        return line

    # ---- stages ----

    @property
    def current_stage(self) -> d.Stage:
        return (self.stages or d.STAGES)[min(self._stage_idx, len(self.stages or d.STAGES) - 1)]

    @property
    def editor_unlocked(self) -> bool:
        """The lock lives here, in agent state, not in the browser.

        A candidate who refreshes the page does not get an editor they have
        not earned: the approach has to be spoken first.
        """
        return bool(self.stages) and self.current_stage.name in d.EDITABLE

    def record_snapshot(self, content: str, language: str = "python") -> None:
        """The editor buffer, roughly every ten seconds."""
        self.code = content
        self.language = language
        self.snapshots.append({"t": self.elapsed(), "content": content})

    def record_test_results(self, passed: int, total: int, categories: list[str]) -> None:
        self.test_results = {"passed": passed, "total": total, "categories": categories}

    def elapsed_in_stage(self) -> float:
        return self.elapsed() - self._stage_started

    def stage_is_over(self) -> bool:
        """Out of time, out of turns, or out of things to ask about."""
        stage = self.current_stage
        if self._stage_turns >= stage.max_turns:
            return True
        if self.elapsed_in_stage() >= stage.budget_s:
            return True
        # the deep dive ends when the coverage map does
        return bool(stage.name == "deep_dive" and self.coverage and not self.coverage.unprobed())

    def should_nudge(self) -> bool:
        """80% of the budget. A nudge, never a cut mid-sentence."""
        if self._nudged or not self.stages:
            return False
        return self.elapsed_in_stage() >= 0.8 * self.current_stage.budget_s

    def advance_stage(self) -> str | None:
        """Move on. Returns the bridge plus the next opening, or None at the end.

        The summary of the finished stage is computed here rather than asked
        for: a model call at a stage boundary is either dead air or a race.
        """
        stages = self.stages or d.STAGES
        finished = self.current_stage
        piece = ctx.summarise_locally(self.transcript, finished.name)
        self.summary = f"{self.summary}\n{piece}".strip()

        self._stage_idx += 1
        if self._stage_idx >= len(stages):
            self.done = True
            return None

        self._stage_started = self.elapsed()
        self._stage_turns = 0
        self._nudged = False
        self.stage = self.current_stage.name
        return f"{finished.bridge} {self.current_stage.opening}"

    def context(self) -> ctx.Context:
        """What goes to the model this turn, in cache-friendly order."""
        return ctx.Context(
            static=self.static_context,
            summary=self.summary,
            recent=ctx.recent_lines(self.transcript),
        )

    async def answer(self, text: str, *, t_start: float | None = None) -> AsyncIterator[str]:
        """Candidate said `text`. Yields the interviewer's reply as it arrives.

        Read `done` after the stream is exhausted. The acknowledgement streams
        from the model; the question that follows it is appended locally, so it
        costs nothing and arrives the instant the model stops.
        """
        end = self.elapsed()
        self._record("candidate", text, t_start if t_start is not None else end, end)

        # everything said during the approach stage IS the approach
        if self.stages and self.current_stage.name == "approach":
            self.approach_text = f"{self.approach_text} {text}".strip()

        decision: Decision | None = None
        if self.coverage is not None:
            routed = time.monotonic()
            decision = await classify(self.llm, self.topic, text, self.coverage)
            self.latency.record("router", int((time.monotonic() - routed) * 1000))
            self.topic = apply_route(decision, self.coverage, self.topic)
            self.decisions.append(decision)

        started = time.monotonic()
        ttft_ms: int | None = None
        parts: list[str] = []

        async for piece in self.llm.stream(d.SYSTEM, text, max_tokens=60):
            if ttft_ms is None:
                ttft_ms = int((time.monotonic() - started) * 1000)
            parts.append(piece)
            yield piece

        self._stage_turns += 1
        tail, is_question = await self._next_line(decision)
        self._last_tail_was_question = is_question
        if not is_question:
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
        # the decision rides with the candidate turn it was made about
        await self._emit(self.transcript[-2], decision)
        await self._emit(self.transcript[-1])

    async def _next_line(self, decision: Decision | None) -> tuple[str, bool]:
        """What the interviewer says after the acknowledgement."""
        coding_line = await self._coding_line()
        if coding_line:
            return coding_line, True

        if self.stages and self.stage_is_over():
            moved = self.advance_stage()
            if moved is None:
                return " " + d.CLOSING, False
            return " " + moved, True

        nudge = ""
        if self.should_nudge():
            self._nudged = True
            nudge = " " + self.current_stage.nudge

        if self.coverage is None:
            # phase 1 behaviour: walk the fixed script
            if self._asked < len(self.questions):
                line = self.questions[self._asked]
                self._asked += 1
                return " " + line, True
            return " " + d.CLOSING, False

        if not self.topic:
            return " " + d.CLOSING, False

        self._asked += 1
        route = decision.route if decision else "pivot"
        return nudge + " " + d.FOLLOW_UP[route].format(topic=self.topic), True

    async def _coding_line(self) -> str:
        """What the coding stages say, when they have something to say.

        Returns "" to fall through to the ordinary stage handling, which is
        what happens during CODING while the candidate is just typing.
        """
        if not self.stages:
            return ""
        stage = self.current_stage.name

        if stage == "test_run" and self.test_results:
            results, self.test_results = self.test_results, None
            _kind, said = review.submit_reaction(results["passed"], results["total"])
            return " " + said

        if stage == "code_review" and not self._reviewed:
            self._reviewed = True
            # the question nothing else can ask
            probe = await review.approach_vs_code(
                self.llm, self.approach_text, self.code, self.language
            )
            if probe:
                return " " + probe
            rewritten = review.rewrite_probe(self.snapshots)
            if rewritten:
                return " " + rewritten
            if self.problem_probes:
                return " " + self.problem_probes[0]

        return ""

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

    async def _emit(self, turn: Turn, decision: Decision | None = None) -> None:
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
                # the live map, so a resumed session does not restart from the
                # pre-session snapshot and the browser can watch it fill
                "coverage_map": self.coverage.model_dump() if self.coverage else None,
                "decision": decision.model_dump() if decision else None,
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
