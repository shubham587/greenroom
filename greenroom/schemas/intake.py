"""What we extract from a resume and a job description.

Shaped by what generates questions, not by what a resume could contain. There
is no address field because no interviewer asks about one.

A `Claim` is the useful unit: a statement the candidate has made in writing
that can be probed. "Rebuilt the order pipeline on Kafka" is a claim; "Python"
is a skill. The interview is mostly made of claims.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Level = Literal["junior", "mid", "senior", "staff"]
Priority = Literal["high", "medium", "low"]
Status = Literal["unprobed", "probed_weak", "covered"]


class Claim(BaseModel):
    text: str = Field(description="the claim in the candidate's own words, verbatim")
    topics: list[str] = Field(default_factory=list, description="technologies or areas it touches")
    quantified: bool = Field(
        default=False, description="whether it carries a number or a concrete outcome"
    )


class Resume(BaseModel):
    name: str | None = None
    years_experience: float | None = None
    skills: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)


class JobDescription(BaseModel):
    title: str
    level: Level = "mid"
    stack: list[str] = Field(default_factory=list, description="languages and major frameworks")
    required: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)


class Topic(BaseModel):
    """One row of the coverage map: something worth asking about."""

    name: str
    source: Literal["resume", "jd", "both", "chased"]
    evidence: str = Field(default="", description="the words it came from")
    priority: Priority = "medium"
    status: Status = "unprobed"


class CoverageMap(BaseModel):
    topics: list[Topic] = Field(default_factory=list)

    def unprobed(self) -> list[Topic]:
        """Highest priority first - what to ask next when a topic is exhausted."""
        order = {"high": 0, "medium": 1, "low": 2}
        return sorted(
            (t for t in self.topics if t.status == "unprobed"),
            key=lambda t: order[t.priority],
        )

    def find(self, name: str) -> Topic | None:
        lowered = name.strip().lower()
        return next((t for t in self.topics if t.name.lower() == lowered), None)

    def add_chased(self, name: str, evidence: str = "") -> Topic:
        """A topic the candidate raised that neither document mentioned.

        This is the human move - following what someone actually said - so it
        goes in the map rather than being answered and forgotten.
        """
        existing = self.find(name)
        if existing:
            return existing
        topic = Topic(name=name, source="chased", evidence=evidence, priority="high")
        self.topics.append(topic)
        return topic
