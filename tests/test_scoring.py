import json

import pytest

from greenroom import rubric
from greenroom.delivery import metrics
from greenroom.scoring import build_prompt, evidence_is_real, score


class ReplyLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.system: str | None = None
        self.user: str | None = None

    async def stream(self, system: str, user: str, *, max_tokens: int = 150):
        self.system, self.user = system, user
        yield self.reply


ANSWER = "I rebuilt the consumer side and cut reprocessing from 40 minutes to 6."


def payload(**kw) -> str:
    base = {
        "dimension": "D5",
        "evidence_span": "cut reprocessing from 40 minutes to 6",
        "score": 4,
        "ideal_answer": "Same, plus why it mattered.",
    }
    return json.dumps({"scores": [{**base, **kw}]})


# ---- the evidence check ----


def test_a_real_quote_is_accepted():
    assert evidence_is_real("cut reprocessing from 40 minutes to 6", ANSWER)


def test_whitespace_and_smart_quotes_are_forgiven():
    assert evidence_is_real("cut  reprocessing   from 40 minutes to 6", ANSWER)
    assert evidence_is_real("I don't know", "well, I don’t know really")


def test_a_paraphrase_is_not_evidence():
    assert not evidence_is_real("reduced reprocessing time significantly", ANSWER)


def test_an_invented_quote_is_not_evidence():
    assert not evidence_is_real("I used Kubernetes for orchestration", ANSWER)


def test_an_empty_span_is_not_evidence():
    assert not evidence_is_real("", ANSWER)
    assert not evidence_is_real("   ", ANSWER)


# ---- scoring end to end with a fake model ----


async def test_a_well_evidenced_score_survives():
    got = await score(ReplyLLM(payload()), "intro", "tell me about your work", ANSWER)
    assert len(got) == 1
    assert got[0].score == 4
    assert got[0].ideal_answer


async def test_a_score_with_fabricated_evidence_is_dropped():
    reply = payload(evidence_span="I led a team of 30 engineers")
    got = await score(ReplyLLM(reply), "intro", "q", ANSWER)
    assert got == [], "a plausible quote that was never said must not reach the report"


async def test_a_dimension_the_stage_cannot_show_is_dropped():
    # D3 is implementation quality; an intro turn cannot demonstrate it
    got = await score(ReplyLLM(payload(dimension="D3")), "intro", "q", ANSWER)
    assert got == []


async def test_an_out_of_range_score_is_rejected_by_the_schema():
    got = await score(ReplyLLM(payload(score=9)), "intro", "q", ANSWER)
    assert got == [], "the schema bounds the scale; 9 is not a rubric score"


async def test_unparseable_output_returns_nothing_rather_than_guessing():
    assert await score(ReplyLLM("sorry, I can't"), "intro", "q", ANSWER) == []


async def test_the_answer_is_fenced_and_the_rubric_anchors_are_supplied():
    llm = ReplyLLM(payload())
    await score(llm, "intro", "q", ANSWER)
    assert llm.user.count("<<<ANSWER>>>") == 2
    assert "D5" in llm.system
    assert "Every claim carries evidence" in llm.system, "the 5 anchor should be in the prompt"


def test_evidence_comes_before_score_in_the_prompt():
    system, _ = build_prompt("intro", "q", ANSWER)
    assert system.index("evidence_span") < system.index('"score"')


# ---- the rubric file ----


def test_all_five_dimensions_parse_with_five_anchors_each():
    dims = rubric.dimensions()
    assert set(dims) == {"D1", "D2", "D3", "D4", "D5"}
    for d in dims.values():
        assert set(d.anchors) == {1, 2, 3, 4, 5}, d.id


@pytest.mark.parametrize(
    ("stage", "expected"),
    [("intro", {"D5"}), ("coding", {"D3"}), ("approach", {"D1", "D2", "D5"})],
)
def test_stages_only_score_what_they_can_show(stage, expected):
    assert {d.id for d in rubric.for_stage(stage)} == expected


# ---- delivery metrics, which need no model ----


def test_delivery_counts_fillers_and_pace():
    turns = [
        {"speaker": "interviewer", "text": "go on", "t_start": 0.0, "t_end": 1.0},
        {
            "speaker": "candidate",
            "text": "um so basically like we just sort of shipped it",
            "t_start": 3.0,
            "t_end": 9.0,
        },
    ]
    m = metrics(turns)
    assert m["turns"] == 1
    assert m["filler_words"] >= 5
    assert m["avg_pause_before_answering_s"] == 2.0
    assert m["longest_answer_s"] == 6.0
    assert m["words_per_minute"] > 0


def test_delivery_on_an_empty_interview_is_empty_not_a_crash():
    assert metrics([]) == {}
    assert metrics([{"speaker": "interviewer", "text": "hi", "t_start": 0, "t_end": 1}]) == {}


async def test_a_dimension_label_is_accepted_not_just_the_bare_id():
    """The prompt prints anchors under "D5 - Communication and evidence", so
    the model echoes the label. That is formatting, not a wrong answer."""
    got = await score(
        ReplyLLM(payload(dimension="D5 - Communication and evidence")), "intro", "q", ANSWER
    )
    assert len(got) == 1
    assert got[0].dimension == "D5", "normalised back to the bare id for storage"


def test_duration_metrics_are_omitted_when_there_are_no_durations():
    """Text mode has no speaking time. Reporting 0.0 s as if measured is a lie."""
    turns = [
        {"speaker": "candidate", "text": "um we shipped it", "t_start": 4.0, "t_end": 4.0},
    ]
    m = metrics(turns)
    assert m["filler_words"] == 1
    assert "words_per_minute" not in m
    assert "longest_answer_s" not in m
