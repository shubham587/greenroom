from dataclasses import replace

from greenroom.stages import definitions as d
from greenroom.stages.machine import StageMachine


class FakeLLM:
    """Answers the review prompt differently from an ordinary acknowledgement.

    The real model sees two quite different system prompts; a fake that
    returns one string for both makes "was the probe asked twice?"
    unanswerable.
    """

    def __init__(self, probe_reply: str = "Noted.") -> None:
        self.probe_reply, self.seen = probe_reply, []

    async def stream(self, system: str, user: str, *, max_tokens: int = 150):
        self.seen.append(user)
        reviewing = "looking at code a candidate just wrote" in system
        yield self.probe_reply if reviewing else "Noted."


async def drain(m: StageMachine, text: str) -> str:
    return "".join([p async for p in m.answer(text)])


def coding_machine(llm=None, stages=None) -> StageMachine:
    return StageMachine(llm=llm or FakeLLM(), stages=stages or list(d.FULL))


# ---- the editor lock ----


def test_the_editor_is_shut_before_the_coding_stage():
    m = coding_machine()
    assert m.current_stage.name == "intro"
    assert not m.editor_unlocked


async def test_the_editor_opens_only_once_an_approach_has_been_spoken():
    m = coding_machine(
        stages=[
            replace(d.PROBLEM, max_turns=1),
            replace(d.APPROACH, max_turns=1),
            d.CODING,
            d.WRAP,
        ]
    )
    m.open()
    assert not m.editor_unlocked, "problem stage"

    await drain(m, "any clarifying question")
    assert m.current_stage.name == "approach"
    assert not m.editor_unlocked, "locked while they explain the plan"

    await drain(m, "Sort by start, then sweep and merge. O(n log n).")
    assert m.current_stage.name == "coding"
    assert m.editor_unlocked, "earned it by saying the approach out loud"


def test_the_lock_is_agent_state_so_a_refresh_cannot_bypass_it():
    m = coding_machine()
    m._stage_idx = [s.name for s in d.FULL].index("approach")
    assert not m.editor_unlocked, "nothing the browser does changes this"


# ---- the approach is captured as its own artifact ----


async def test_everything_said_during_approach_becomes_the_approach():
    m = coding_machine(stages=[replace(d.APPROACH, max_turns=9), d.CODING, d.WRAP])
    m.open()
    await drain(m, "I'd sort by start.")
    await drain(m, "Then sweep and merge, which is n log n.")

    assert "sort by start" in m.approach_text.lower()
    assert "sweep and merge" in m.approach_text.lower()


async def test_talking_during_coding_does_not_pollute_the_approach():
    m = coding_machine(stages=[replace(d.CODING, max_turns=9), d.WRAP])
    m.open()
    await drain(m, "just thinking out loud here")
    assert m.approach_text == "", "only the approach stage records the approach"


# ---- snapshots ----


def test_snapshots_keep_history_and_the_latest_code():
    m = coding_machine()
    m.record_snapshot("def merge(x): pass")
    m.record_snapshot("def merge(x):\n    return sorted(x)")

    assert len(m.snapshots) == 2
    assert m.code.endswith("sorted(x)"), "latest wins"
    assert m.snapshots[0]["t"] <= m.snapshots[1]["t"]


# ---- reacting to a submit ----


async def test_the_interviewer_reacts_to_the_test_results():
    m = coding_machine(stages=[replace(d.TEST_RUN, max_turns=9), d.WRAP])
    m.open()
    m.record_test_results(passed=6, total=8, categories=["edge", "edge"])

    said = await drain(m, "I've submitted.")
    assert "6 of 8" in said
    assert "what class of input" in said


async def test_results_are_reacted_to_once_not_every_turn():
    m = coding_machine(stages=[replace(d.TEST_RUN, max_turns=9), d.WRAP])
    m.open()
    m.record_test_results(passed=6, total=8, categories=["edge"])

    await drain(m, "submitted")
    second = await drain(m, "maybe empty input?")
    assert "6 of 8" not in second, "it should move on, not repeat the scoreboard"


# ---- the probe that is the point of the whole phase ----


async def test_the_review_compares_what_was_said_to_what_was_written():
    llm = FakeLLM("You said a hash map but wrote nested loops - what changed?")
    m = coding_machine(llm=llm, stages=[replace(d.CODE_REVIEW, max_turns=9), d.WRAP])
    m.open()
    m.approach_text = "I'll use a hash map for the lookups."
    m.record_snapshot("for a in xs:\n    for b in xs:\n        ...")

    said = await drain(m, "I think it's done.")

    assert "hash map" in said and "nested loops" in said
    # both sides really were handed to the model
    probe_prompt = llm.seen[-1]
    assert "hash map" in probe_prompt
    assert "for a in xs" in probe_prompt


async def test_the_review_falls_back_when_there_is_no_approach_to_compare():
    m = coding_machine(llm=FakeLLM(), stages=[replace(d.CODE_REVIEW, max_turns=9), d.WRAP])
    m.open()
    m.problem_probes = ["What's your complexity, and where does the sort land in it?"]
    # no approach captured, so the comparison cannot be made
    said = await drain(m, "done")
    assert "complexity" in said


async def test_the_review_probe_is_asked_once():
    llm = FakeLLM("You said X but wrote Y")
    m = coding_machine(llm=llm, stages=[replace(d.CODE_REVIEW, max_turns=9), d.WRAP])
    m.open()
    m.approach_text = "a plan"
    m.record_snapshot("some code")

    await drain(m, "one")
    second = await drain(m, "two")
    assert "You said X but wrote Y" not in second


# ---- the whole run still holds together ----


async def test_a_full_eight_stage_interview_reaches_the_end():
    m = coding_machine(stages=[replace(s, max_turns=1) for s in d.FULL])
    m.open()
    for i in range(len(d.FULL)):
        await drain(m, f"answer {i}")
        if m.done:
            break
    assert m.done, "it must terminate rather than loop"
