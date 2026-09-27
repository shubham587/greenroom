import pytest

from greenroom.routing import apply, classify, heuristic
from greenroom.schemas.intake import CoverageMap, Topic
from greenroom.schemas.routing import Decision


class ReplyLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.user: str | None = None

    async def stream(self, system: str, user: str, *, max_tokens: int = 150):
        self.user = user
        yield self.reply


def a_map() -> CoverageMap:
    return CoverageMap(
        topics=[
            Topic(name="Kafka", source="both", priority="high"),
            Topic(name="Postgres", source="jd", priority="high"),
            Topic(name="Docker", source="jd", priority="low"),
        ]
    )


# ---- the classifier ----


async def test_a_valid_decision_is_used_as_given():
    llm = ReplyLLM('{"route":"drill","reason":"strong and specific","topic":"Kafka"}')
    d = await classify(
        llm, "Kafka", "I rebuilt the consumer side, cut lag from 40s to 2s.", a_map()
    )
    assert d.route == "drill"
    assert d.reason


async def test_the_answer_is_fenced_and_unprobed_topics_are_offered():
    llm = ReplyLLM('{"route":"pivot","reason":"done here","topic":""}')
    await classify(llm, "Kafka", "some answer", a_map())
    assert llm.user.count("<<<ANSWER>>>") == 2
    assert "Postgres" in llm.user, "the model needs to know what is still unasked"


async def test_nonsense_from_the_model_falls_back_instead_of_crashing():
    d = await classify(ReplyLLM("not json"), "Kafka", "I don't know, never used it.", a_map())
    assert d.route == "rescue", "the heuristic should still do something sensible"


async def test_an_empty_topic_from_the_model_is_filled_in():
    llm = ReplyLLM('{"route":"drill","reason":"ok","topic":""}')
    d = await classify(llm, "Kafka", "a long substantive answer with 400 ms in it", a_map())
    assert d.topic == "Kafka"


# ---- the heuristic on its own ----


@pytest.mark.parametrize(
    ("answer", "route"),
    [
        ("Yes.", "probe"),
        ("I don't know, I have never used it.", "rescue"),
        ("We used a queue and it was fine and reliable and good for us", "probe"),
        ("We cut p99 from 800 ms to 120 ms by batching writes into 50 row chunks", "drill"),
    ],
)
def test_heuristic_routes(answer: str, route: str):
    assert heuristic(answer).route == route


# ---- applying a decision to the map ----


def test_drill_stays_on_the_topic_and_marks_it_covered():
    m = a_map()
    nxt = apply(Decision(route="drill", reason="x"), m, "Kafka")
    assert nxt == "Kafka"
    assert m.find("Kafka").status == "covered"


def test_probe_stays_on_the_topic_but_leaves_it_weak():
    m = a_map()
    nxt = apply(Decision(route="probe", reason="vague"), m, "Kafka")
    assert nxt == "Kafka"
    assert m.find("Kafka").status == "probed_weak", "a vague answer has not covered the ground"


def test_chase_adds_the_new_topic_and_goes_there():
    m = a_map()
    nxt = apply(
        Decision(route="chase", reason="they raised it", topic="event sourcing"), m, "Kafka"
    )
    assert nxt == "event sourcing"
    assert m.find("event sourcing").source == "chased"
    assert m.find("Kafka").status == "covered"


def test_pivot_takes_the_highest_priority_unasked_topic():
    m = a_map()
    nxt = apply(Decision(route="pivot", reason="exhausted"), m, "Kafka")
    assert nxt == "Postgres", "high priority before the low-priority Docker"
    assert m.find("Kafka").status == "covered"


def test_pivot_with_nothing_left_returns_empty_rather_than_looping():
    m = CoverageMap(topics=[Topic(name="Kafka", source="jd", status="covered")])
    assert apply(Decision(route="pivot", reason="done"), m, "Kafka") == ""


def test_rescue_keeps_the_topic_open():
    m = a_map()
    nxt = apply(Decision(route="rescue", reason="floundering"), m, "Kafka")
    assert nxt == "Kafka"
    assert m.find("Kafka").status == "probed_weak"


def test_the_map_converges_rather_than_asking_forever():
    m = a_map()
    topic = "Kafka"
    for _ in range(10):
        topic = apply(Decision(route="pivot", reason="next"), m, topic)
        if not topic:
            break
    assert all(t.status == "covered" for t in m.topics)
    assert topic == ""


def test_drill_follows_what_the_answer_was_actually_about():
    """The opening topic is whatever sorted first, which need not be the
    subject of the answer. Following the classifier keeps it coherent."""
    m = a_map()
    nxt = apply(Decision(route="probe", reason="vague", topic="order events pipeline"), m, "Python")
    assert nxt == "order events pipeline"
    assert m.find("order events pipeline") is not None


def test_staying_on_the_same_topic_does_not_duplicate_it():
    m = a_map()
    before = len(m.topics)
    assert apply(Decision(route="drill", reason="x", topic="kafka"), m, "Kafka") == "Kafka"
    assert len(m.topics) == before, "same topic in different case must not be added twice"
