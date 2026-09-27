"""What the interviewer decides after hearing an answer.

Five routes, because that is what a person actually does: press on something
strong, press on something vague, follow something new, change subject, or
help someone who is drowning.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Route = Literal["drill", "probe", "chase", "pivot", "rescue"]

ROUTE_MEANING: dict[str, str] = {
    "drill": "the answer was strong - go one level deeper on the same topic",
    "probe": "the answer was vague, buzzword-heavy, or made an unquantified claim",
    "chase": "the candidate raised something neither document mentioned - follow it",
    "pivot": "this topic is exhausted - move to the highest-priority unprobed one",
    "rescue": "the candidate is floundering - hint down and preserve their dignity",
}


class Decision(BaseModel):
    route: Route
    reason: str = Field(description="one short clause, in plain words")
    topic: str = Field(
        default="",
        description=(
            "what the answer was actually about, two or three words - not necessarily "
            "what was asked, because candidates answer the question they wanted"
        ),
    )
