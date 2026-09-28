"""Scoring one answer, with the evidence checked against what was said.

The interesting constraint is not the score, it is the span. A judge that
can quote anything will quote something plausible, and a plausible quote is
indistinguishable from a real one in a report. So every span is verified to
be in the transcript, and a score whose evidence is not there is dropped.
That turns "trust the model" into "check the model", which is the whole
difference between a scoring feature and a scoring system.
"""

from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, Field, ValidationError

from greenroom import prompts, rubric
from greenroom.llm.client import LLM, complete

log = logging.getLogger(__name__)


class TurnScore(BaseModel):
    dimension: str
    # evidence first, in the schema as in the prompt: the order is the point
    evidence_span: str
    score: int = Field(ge=1, le=5)
    ideal_answer: str = ""


class ScoreSet(BaseModel):
    scores: list[TurnScore] = Field(default_factory=list)


def _normalise(text: str) -> str:
    """Whitespace and smart quotes differ between speech-to-text and the model."""
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


def _dimension_id(raw: str) -> str:
    """ "D5 - Communication and evidence" -> "D5". Anything else, unchanged."""
    match = re.match(r"\s*(D\d)\b", raw)
    return match.group(1) if match else raw.strip()


def evidence_is_real(span: str, answer: str) -> bool:
    """Is this quote actually in what the candidate said?

    Exact-ish: whitespace and quote characters are allowed to differ, nothing
    else. A model that paraphrases has invented the evidence, and invented
    evidence in a report is worse than no evidence.
    """
    if not span.strip():
        return False
    return _normalise(span) in _normalise(answer)


def build_prompt(stage: str, question: str, answer: str) -> tuple[str, str]:
    system = f"{prompts.load('scorer')}\n\n## Dimensions to score\n\n{rubric.prompt_block(stage)}"
    user = (
        f"Stage: {stage}\n"
        f"The interviewer asked: {question}\n\n"
        f"<<<ANSWER>>>\n{answer.replace('<<<ANSWER>>>', '')}\n<<<ANSWER>>>"
    )
    return system, user


async def score(llm: LLM, stage: str, question: str, answer: str) -> list[TurnScore]:
    """Score one answer. Returns only the dimensions whose evidence checks out."""
    system, user = build_prompt(stage, question, answer)

    try:
        raw = await complete(llm, system, user, max_tokens=1200)
        body = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        parsed = ScoreSet.model_validate_json(body)
    except (ValidationError, json.JSONDecodeError, ValueError) as exc:
        log.warning("scorer returned nothing usable: %s", exc)
        return []

    wanted = {d.id for d in rubric.for_stage(stage)}
    kept: list[TurnScore] = []
    for s in parsed.scores:
        # the prompt prints anchors under "D5 - Communication and evidence",
        # so the model tends to echo the whole label back. That is a cosmetic
        # difference, not a wrong answer - be strict about the evidence, not
        # about formatting.
        s.dimension = _dimension_id(s.dimension)
        if s.dimension not in wanted:
            log.warning("scorer returned dimension %r, not valid for stage %s", s.dimension, stage)
            continue
        if not evidence_is_real(s.evidence_span, answer):
            log.warning(
                "dropping %s: evidence not in the transcript: %r", s.dimension, s.evidence_span[:60]
            )
            continue
        kept.append(s)
    return kept
