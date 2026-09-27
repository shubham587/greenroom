import asyncio

from greenroom.stages import definitions as d
from greenroom.stages.machine import StageMachine


class FakeLLM:
    """Records what it was asked, and streams in pieces like a real one."""

    def __init__(self, delay: float = 0.0) -> None:
        self.seen: list[str] = []
        self.delay = delay

    async def stream(self, system: str, user: str, *, max_tokens: int = 150):
        self.seen.append(user)
        for piece in ("No", "ted", "."):
            if self.delay:
                await asyncio.sleep(self.delay)
            yield piece


async def drain(machine: StageMachine, text: str) -> str:
    return "".join([p async for p in machine.answer(text)])


async def test_walks_the_script_then_finishes():
    llm = FakeLLM()
    m = StageMachine(llm=llm)

    assert m.open() == d.OPENING

    assert d.QUESTIONS[0] in await drain(m, "I built an events pipeline.")
    assert not m.done

    assert d.QUESTIONS[1] in await drain(m, "I owned the consumer side.")
    assert not m.done

    last = await drain(m, "I'd use a different partition key.")
    assert m.done
    assert d.CLOSING in last

    # the model saw the candidate's words, not a template
    assert llm.seen == [
        "I built an events pipeline.",
        "I owned the consumer side.",
        "I'd use a different partition key.",
    ]


async def test_reply_arrives_in_pieces_not_one_blob():
    m = StageMachine(llm=FakeLLM())
    m.open()
    pieces = [p async for p in m.answer("something")]
    # three from the model, then the appended question
    assert len(pieces) > 1
    assert pieces[-1].strip() == d.QUESTIONS[0]


async def test_first_token_is_measured_earlier_than_the_whole_reply():
    m = StageMachine(llm=FakeLLM(delay=0.02))
    m.open()
    await drain(m, "something")

    turn = m.transcript[-1]
    assert turn.speaker == "interviewer"
    assert turn.ttft_ms is not None and turn.think_ms is not None
    # the point of streaming: first word lands well before the last
    assert turn.ttft_ms < turn.think_ms


async def test_transcript_alternates_and_times_every_turn():
    m = StageMachine(llm=FakeLLM())
    m.open()
    await drain(m, "one")
    await drain(m, "two")

    speakers = [t.speaker for t in m.transcript]
    assert speakers == ["interviewer", "candidate", "interviewer", "candidate", "interviewer"]
    assert all(t.t_end >= t.t_start for t in m.transcript)

    out = m.format_transcript()
    assert "first token" in out
    assert "candidate" in out


async def test_latencies_reports_per_layer_percentiles():
    m = StageMachine(llm=FakeLLM(delay=0.01))
    m.open()
    await drain(m, "one")
    await drain(m, "two")

    lat = m.latencies()
    assert lat["turns"] == 2
    assert lat["llm_ttft_p50"] <= lat["llm_full_p50"]
    assert lat["llm_ttft_p95"] >= lat["llm_ttft_p50"]


async def test_stub_llm_lets_the_interview_run_with_no_api_key():
    from greenroom.llm.client import StubLLM

    m = StageMachine(llm=StubLLM())
    m.open()
    assert await drain(m, "something")


async def test_backchannel_is_not_an_answer():
    from greenroom.stages.machine import is_backchannel

    # agreement noises made over the interviewer
    assert is_backchannel("Yes, that is correct.")
    assert is_backchannel("yeah")
    assert is_backchannel("Okay right")
    assert is_backchannel("Got it")

    # real answers, however short
    assert not is_backchannel("I owned the consumer side.")
    assert not is_backchannel("Kafka")
    assert not is_backchannel("Yes, because the partition key was skewed.")
    assert not is_backchannel("")


async def test_interrupted_question_is_asked_again():
    m = StageMachine(llm=FakeLLM())
    m.open()

    first = await drain(m, "I built a pipeline.")
    assert d.QUESTIONS[0] in first

    # the candidate talked over it, so they never heard the question
    assert m.rewind_question() is True

    second = await drain(m, "sorry, go on")
    assert d.QUESTIONS[0] in second, "the unheard question should come back"

    # and rewinding twice in a row does nothing the second time
    assert m.rewind_question() is True
    assert m.rewind_question() is False


async def test_rewind_does_not_reopen_a_finished_interview():
    m = StageMachine(llm=FakeLLM())
    m.open()
    await drain(m, "one")
    await drain(m, "two")
    await drain(m, "three")
    assert m.done
    # the closing line is not a question, so there is nothing to re-ask
    assert m.rewind_question() is False
    assert m.done
