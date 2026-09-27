"""The coding problem bank.

Static YAML verified offline by scripts/seed.py. Nothing here generates a
test at runtime: a wrong generated test tells a candidate their correct
solution is broken, which is the worst thing this product can do.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from greenroom.schemas.intake import JobDescription, Level

BANK = Path("problems")


class Test(BaseModel):
    name: str
    input: list = Field(default_factory=list)
    expected: object = None
    visible: bool = False
    category: Literal["happy", "edge", "perf"] = "happy"


class Problem(BaseModel):
    id: str
    title: str
    difficulty: Literal["easy", "medium", "hard"]
    tags: list[str] = Field(default_factory=list)
    level: list[Level] = Field(default_factory=list)
    statement: str
    signature: dict[str, str]
    reference: dict[str, str]
    probes: list[str] = Field(default_factory=list)
    tests: list[Test] = Field(default_factory=list)
    equivalent_mutations: list[str] = Field(
        default_factory=list,
        description=(
            "mutations that produce identical behaviour for this algorithm, so no test "
            "can catch them. Each needs a comment in the YAML saying why - this is an "
            "exemption from the mutation check and should be argued, not assumed."
        ),
    )

    @property
    def visible_tests(self) -> list[Test]:
        return [t for t in self.tests if t.visible]

    @property
    def hidden_tests(self) -> list[Test]:
        """Never shown to the candidate - only the count and the category.

        Reveal the inputs and they patch the test instead of the bug, which
        throws away the most valuable moment in the interview.
        """
        return [t for t in self.tests if not t.visible]


@lru_cache(maxsize=1)
def load_all(directory: str | None = None) -> tuple[Problem, ...]:
    path = Path(directory) if directory else BANK
    problems = []
    for f in sorted(path.glob("*.yaml")):
        problems.append(Problem.model_validate(yaml.safe_load(f.read_text())))
    return tuple(problems)


def select(jd: JobDescription, directory: str | None = None) -> Problem | None:
    """Pick a problem for this job: right level first, then overlapping stack."""
    problems = load_all(directory)
    if not problems:
        return None

    wanted = {s.lower() for s in (*jd.stack, *jd.required)}

    def score(p: Problem) -> tuple[int, int]:
        fits_level = jd.level in p.level
        overlap = len(wanted & {t.lower() for t in p.tags})
        return (0 if fits_level else 1, -overlap)  # lower sorts first

    return sorted(problems, key=score)[0]
