import json

from greenroom.llm.cassette import CassetteLLM


class CountingLLM:
    def __init__(self, reply: str = "Noted.") -> None:
        self.calls = 0
        self.reply = reply

    async def stream(self, system: str, user: str, *, max_tokens: int = 150):
        self.calls += 1
        for piece in self.reply.split(" "):
            yield piece + " "


async def drain(llm, system="sys", user="hello", **kw):
    return "".join([c async for c in llm.stream(system, user, **kw)])


async def test_replay_calls_the_model_once_then_serves_from_disk(tmp_path):
    inner = CountingLLM()
    c = CassetteLLM(inner, "m", "replay", tmp_path)

    first = await drain(c)
    assert inner.calls == 1

    second = await drain(c)
    assert inner.calls == 1, "second identical call must not reach the model"
    assert second == first


async def test_a_changed_prompt_misses_and_records_itself(tmp_path):
    inner = CountingLLM()
    c = CassetteLLM(inner, "m", "replay", tmp_path)

    await drain(c, user="first question")
    await drain(c, user="second question")
    assert inner.calls == 2

    # both are now cached
    await drain(c, user="first question")
    await drain(c, user="second question")
    assert inner.calls == 2


async def test_max_tokens_is_part_of_the_key(tmp_path):
    inner = CountingLLM()
    c = CassetteLLM(inner, "m", "replay", tmp_path)

    await drain(c, max_tokens=60)
    await drain(c, max_tokens=150)
    assert inner.calls == 2, "a different budget is a different call"


async def test_model_is_part_of_the_key(tmp_path):
    inner = CountingLLM()
    await drain(CassetteLLM(inner, "model-a", "replay", tmp_path))
    await drain(CassetteLLM(inner, "model-b", "replay", tmp_path))
    assert inner.calls == 2


async def test_record_mode_always_calls_but_still_writes(tmp_path):
    inner = CountingLLM()
    c = CassetteLLM(inner, "m", "record", tmp_path)

    await drain(c)
    await drain(c)
    assert inner.calls == 2, "record re-records rather than serving stale audio"
    assert len(list(tmp_path.glob("*.json"))) == 1


async def test_off_mode_writes_nothing(tmp_path):
    inner = CountingLLM()
    c = CassetteLLM(inner, "m", "off", tmp_path)

    await drain(c)
    assert inner.calls == 1
    assert list(tmp_path.glob("*.json")) == []


async def test_cassette_is_readable_so_it_can_serve_as_a_fixture(tmp_path):
    inner = CountingLLM("You rebuilt the pipeline.")
    c = CassetteLLM(inner, "m", "replay", tmp_path)
    await drain(c, system="be an interviewer", user="I built a pipeline")

    saved = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert saved["system"] == "be an interviewer"
    assert saved["user"] == "I built a pipeline"
    assert "".join(saved["chunks"]).strip() == "You rebuilt the pipeline."
    assert saved["model"] == "m"
    assert saved["recorded_at"]


async def test_chunks_are_preserved_not_flattened(tmp_path):
    inner = CountingLLM("one two three")
    c = CassetteLLM(inner, "m", "replay", tmp_path)
    await drain(c)

    replayed = [chunk async for chunk in c.stream("sys", "hello")]
    assert len(replayed) == 3, "replay must stream in pieces, like the real thing"
