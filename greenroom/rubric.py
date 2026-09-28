"""The rubric, read from rubric.md so there is one copy of it.

The file at the repo root is the human-readable version a reviewer scores by
hand in phase 8. Parsing it rather than restating it in Python means the
scorer and the hand-scorer can never drift apart, which is the only way the
agreement number means anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

RUBRIC_FILE = Path(__file__).resolve().parents[1] / "rubric.md"

# Which dimensions a stage can speak to. An Approach turn cannot show
# implementation quality, and scoring it anyway invents a number.
STAGE_DIMENSIONS: dict[str, list[str]] = {
    "intro": ["D5"],
    "problem": ["D1", "D5"],
    "approach": ["D1", "D2", "D5"],
    "coding": ["D3"],
    "test_run": ["D4", "D5"],
    "code_review": ["D2", "D3", "D5"],
    "deep_dive": ["D5"],
    "wrap": ["D5"],
}


@dataclass(frozen=True)
class Dimension:
    id: str
    name: str
    anchors: dict[int, str]

    def as_prompt(self) -> str:
        lines = [f"{self.id} - {self.name}"]
        lines += [f"  {score}: {text}" for score, text in sorted(self.anchors.items())]
        return "\n".join(lines)


@lru_cache(maxsize=1)
def dimensions() -> dict[str, Dimension]:
    """Parse the `## D1 · Name` sections and their 1-5 anchor tables."""
    text = RUBRIC_FILE.read_text()
    out: dict[str, Dimension] = {}

    sections = re.split(r"^## (D\d) · (.+)$", text, flags=re.M)[1:]
    for i in range(0, len(sections), 3):
        did, name, body = sections[i], sections[i + 1].strip(), sections[i + 2]
        anchors = {
            int(score): anchor.strip()
            for score, anchor in re.findall(r"^\|\s*(\d)\s*\|\s*(.+?)\s*\|$", body, flags=re.M)
        }
        if anchors:
            out[did] = Dimension(id=did, name=name, anchors=anchors)
    return out


def for_stage(stage: str) -> list[Dimension]:
    dims = dimensions()
    return [dims[d] for d in STAGE_DIMENSIONS.get(stage, ["D5"]) if d in dims]


def prompt_block(stage: str) -> str:
    return "\n\n".join(d.as_prompt() for d in for_stage(stage))
