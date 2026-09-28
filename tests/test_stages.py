from dataclasses import replace

from greenroom.stages import context as ctx
from greenroom.stages import definitions as d
from greenroom.stages.machine import StageMachine


class FakeLLM:
    async def stream(self, system: str, user: str, *, max_tokens: int = 150):
        yield "Noted."


async def drain(m: StageMachine, text: str) -> str:
    return "".join([p async for p in m.answer(text)])


def staged(stages: list[d.Stage] | None = None, **kw) -> StageMachine:
    return StageMachine(llm=FakeLLM(), stages=stages or list(d.STAGES), **kw)


# ---- moving through stages ----


async def test_a_stage_ends_when_it_runs_out_of_turns():
    m = staged()
    m.open()
    assert m.current_stage.name == "intro"

    for _ in range(d.INTRO.max_turns):
        await drain(m, "an answer")

    assert m.current_stage.name == "deep_dive", "intro has a two-turn budget"


async def test_a_stage_ends_when_it_runs_out_of_time():
    m = staged(stages=[replace(d.INTRO, budget_s=0.0), d.DEEP_DIVE, d.WRAP])
    m.open()
    await drain(m, "an answer")
    assert m.current_stage.name == "deep_dive"


async def test_the_bridge_and_the_next_opening_are_spoken_together():
    m = staged(stages=[replace(d.INTRO, max_turns=1), d.DEEP_DIVE, d.WRAP])
    m.open()
    said = await drain(m, "an answer")
    assert d.INTRO.bridge in said, "it should acknowledge the stage ending"
    assert d.DEEP_DIVE.opening in said, "and open the next one in the same breath"


async def test_the_interview_ends_after_the_last_stage():
    m = staged(stages=[replace(d.INTRO, max_turns=1), replace(d.WRAP, max_turns=1)])
    m.open()
    await drain(m, "one")  # intro -> wrap
    assert not m.done
    last = await drain(m, "two")  # wrap is the last stage
    assert m.done
    assert d.CLOSING in last


async def test_a_stage_change_is_recorded_so_a_crash_can_resume():
    m = staged(stages=[replace(d.INTRO, max_turns=1), d.DEEP_DIVE, d.WRAP])
    m.open()
    await drain(m, "an answer")
    assert m.stage == "deep_dive", "the machine's stage field is what gets persisted"


# ---- the nudge ----


async def test_a_nudge_arrives_at_80_percent_rather_than_a_hard_cut():
    m = StageMachine(
        llm=FakeLLM(),
        stages=[replace(d.DEEP_DIVE, budget_s=0.0, max_turns=99), d.WRAP],
    )
    m.open()
    m.topic = "Kafka"
    from greenroom.schemas.intake import CoverageMap, Topic

    m.coverage = CoverageMap(topics=[Topic(name="Kafka", source="jd")])

    assert m.should_nudge(), "past 80% of the budget"


async def test_a_nudge_is_only_given_once_per_stage():
    m = staged(stages=[replace(d.INTRO, budget_s=0.0, max_turns=99), d.WRAP])
    m.open()
    assert m.should_nudge()
    m._nudged = True
    assert not m.should_nudge()


# ---- context stays bounded ----


def test_only_the_last_few_turns_are_sent_verbatim():
    class T:
        def __init__(self, i):
            self.speaker, self.text = "candidate", f"answer {i}"

    lines = ctx.recent_lines([T(i) for i in range(20)])
    assert len(lines) == ctx.VERBATIM_TURNS
    assert "answer 19" in lines[-1], "the most recent turn must be in there"


async def test_context_stops_growing_once_the_summary_takes_over():
    m = staged(stages=[replace(d.INTRO, max_turns=2), replace(d.DEEP_DIVE, max_turns=40), d.WRAP])
    m.static_context = "Role: Backend Engineer"
    m.open()

    sizes = []
    for i in range(14):
        await drain(m, f"this is answer number {i} and it is a reasonably long sentence")
        sizes.append(m.context().size())

    # it grows while filling the verbatim window, then levels off
    later = sizes[-5:]
    assert max(later) - min(later) < 400, f"context should be bounded, saw {later}"


def test_static_content_comes_first_so_the_prefix_caches():
    c = ctx.Context(static="Role: Backend", summary="earlier things", recent=["candidate: hi"])
    out = c.render()
    assert out.index("Role: Backend") < out.index("earlier things") < out.index("candidate: hi")


def test_a_summary_of_a_stage_needs_no_model_call():
    class T:
        def __init__(self, sp, tx):
            self.speaker, self.text = sp, tx

    summary = ctx.summarise_locally(
        [T("interviewer", "q"), T("candidate", "I rebuilt the pipeline")], "intro"
    )
    assert "intro" in summary
    assert "rebuilt the pipeline" in summary


# ---- the phase 1 path still works ----


async def test_without_stages_it_walks_the_fixed_script():
    m = StageMachine(llm=FakeLLM())
    m.open()
    assert d.QUESTIONS[0] in await drain(m, "one")
    assert d.QUESTIONS[1] in await drain(m, "two")
    assert d.CLOSING in await drain(m, "three")
    assert m.done
