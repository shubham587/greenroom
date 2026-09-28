"""The five tables that carry the whole product.

Deliberately not more. Coverage map, resume and job description live as JSON
on the session rather than as their own tables: nothing queries inside them,
and a shape that is still changing every phase does not want a migration each
time it does.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Session(Base):
    """One interview. `state` is the only thing another process needs to resume."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_id)
    # created -> parsing -> ready -> live -> completed -> reported, plus
    # failed and abandoned as terminal branches
    state: Mapped[str] = mapped_column(String(16), default="created", index=True)
    stage: Mapped[str | None] = mapped_column(String(24), nullable=True)

    resume_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    jd_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    coverage_map: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    problem_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    turns: Mapped[list[Turn]] = relationship(back_populates="session", cascade="all, delete-orphan")


class Turn(Base):
    """One thing somebody said. Written the moment it completes, so no failure
    after minute one can cost the whole session."""

    __tablename__ = "turns"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)

    stage: Mapped[str] = mapped_column(String(24))
    speaker: Mapped[str] = mapped_column(String(12))  # interviewer | candidate
    text: Mapped[str] = mapped_column(Text)

    t_start: Mapped[float] = mapped_column(Float)  # seconds since the interview opened
    t_end: Mapped[float] = mapped_column(Float)
    ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    think_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    audio_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped[Session] = relationship(back_populates="turns")


class Decision(Base):
    """Why the interviewer asked what it asked next.

    The inspectable trace: "how does it decide?" should be a query, not a
    reading of the prompt.
    """

    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_id)
    turn_id: Mapped[str] = mapped_column(ForeignKey("turns.id"), index=True)

    route: Mapped[str] = mapped_column(String(16))  # drill | probe | chase | pivot | rescue
    reason: Mapped[str] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Evaluation(Base):
    """One rubric dimension scored against one turn, with the words that justify it."""

    __tablename__ = "evaluations"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_id)
    turn_id: Mapped[str] = mapped_column(ForeignKey("turns.id"), index=True)

    dimension: Mapped[str] = mapped_column(String(48))
    score: Mapped[int] = mapped_column(Integer)
    evidence_span: Mapped[str] = mapped_column(Text)
    ideal_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # the git blob hash of the prompt file, so a score is always attributable
    prompt_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CodeSnap(Base):
    """The editor buffer every ~10 s, so the review can ask about the process
    and not only the final file."""

    __tablename__ = "code_snaps"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)

    t: Mapped[float] = mapped_column(Float)  # seconds since the interview opened
    language: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Report(Base):
    """The thing the candidate reads. One per session.

    Written by the finaliser once every turn has been scored, so it is a
    snapshot rather than something the UI recomputes.
    """

    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True, unique=True)

    narrative: Mapped[str] = mapped_column(Text, default="")
    # {"D1": {"score": 3.5, "n": 2}, ...}
    dimension_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    # filler words, pace, pauses - arithmetic, no model involved
    delivery: Mapped[dict] = mapped_column(JSON, default=dict)
    coverage: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    prompt_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
