import pytest

from greenroom.stages import definitions as d
from greenroom.stages.machine import StageMachine


class FakeLLM:
    """Records what it was asked, so we can assert the machine grounds on the answer."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def complete(self, system: str, user: str, *, max_tokens: int = 150) -> str:
        self.seen.append(user)
        return "Noted."


@pytest.mark.asyncio
async def test_walks_the_script_then_finishes():
    llm = FakeLLM()
    m = StageMachine(llm=llm)

    assert m.open().text == d.OPENING

    first = await m.answer("I built an events pipeline.")
    assert not first.done
    assert d.QUESTIONS[0] in first.text

    second = await m.answer("I owned the consumer side.")
    assert not second.done
    assert d.QUESTIONS[1] in second.text

    # script exhausted -> the next answer closes the interview
    last = await m.answer("I'd use a different partition key.")
    assert last.done
    assert d.CLOSING in last.text

    # the model saw the candidate's words, not a template
    assert llm.seen == [
        "I built an events pipeline.",
        "I owned the consumer side.",
        "I'd use a different partition key.",
    ]


@pytest.mark.asyncio
async def test_transcript_alternates_and_times_every_turn():
    m = StageMachine(llm=FakeLLM())
    m.open()
    await m.answer("one")
    await m.answer("two")

    speakers = [t.speaker for t in m.transcript]
    assert speakers == ["interviewer", "candidate", "interviewer", "candidate", "interviewer"]

    assert all(t.t_end >= t.t_start for t in m.transcript)
    # only interviewer turns carry think time, and every one of them does
    assert all((t.think_ms is not None) == (t.speaker == "interviewer") for t in m.transcript[1:])

    out = m.format_transcript()
    assert "think time" in out
    assert "candidate" in out


@pytest.mark.asyncio
async def test_stub_llm_lets_the_interview_run_with_no_api_key():
    from greenroom.llm.client import StubLLM

    m = StageMachine(llm=StubLLM())
    m.open()
    assert (await m.answer("something")).text
