"""Turning a finished interview into the thing the candidate reads.

The interesting part is the first step. Scoring runs asynchronously, so when
a session ends some turns are still in flight. Tracking that with a Celery
chord does not work here: the agent that queued those tasks has exited and
its task ids went with it. Comparing counts is stateless, survives a worker
restart, and needs no bookkeeping across processes.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select

from greenroom import prompts
from greenroom.db.models import Evaluation, Report, Session, Turn
from greenroom.db.session import db
from greenroom.delivery import metrics
from greenroom.llm.client import complete, get_llm
from greenroom.worker.app import app

log = logging.getLogger(__name__)


def scoring_outstanding(s, session_id: str) -> int:
    """Candidate turns that no evaluation refers to yet."""
    answered = s.scalar(
        select(func.count(Turn.id)).where(
            Turn.session_id == session_id, Turn.speaker == "candidate"
        )
    )
    scored = s.scalar(
        select(func.count(func.distinct(Evaluation.turn_id)))
        .select_from(Evaluation)
        .join(Turn, Turn.id == Evaluation.turn_id)
        .where(Turn.session_id == session_id)
    )
    return (answered or 0) - (scored or 0)


def _aggregate(rows: list[Evaluation]) -> dict:
    by_dim: dict[str, list[int]] = {}
    for r in rows:
        by_dim.setdefault(r.dimension, []).append(r.score)
    return {
        dim: {"score": round(sum(v) / len(v), 2), "n": len(v)} for dim, v in sorted(by_dim.items())
    }


@app.task(
    name="greenroom.worker.finalize_report",
    bind=True,
    acks_late=True,
    max_retries=12,
    default_retry_delay=5,
)
def finalize_report(self, session_id: str) -> str:
    with db() as s:
        outstanding = scoring_outstanding(s, session_id)

    if outstanding > 0:
        log.info("session %s: %d turns still being scored", session_id, outstanding)
        # not an error - the scoring queue is simply still working
        raise self.retry(countdown=5)

    with db() as s:
        session = s.get(Session, session_id)
        if session is None:
            log.warning("finalize_report: no session %s", session_id)
            return session_id

        turns = s.query(Turn).filter(Turn.session_id == session_id).order_by(Turn.t_start).all()
        evals = (
            s.query(Evaluation)
            .join(Turn, Turn.id == Evaluation.turn_id)
            .filter(Turn.session_id == session_id)
            .all()
        )
        turn_dicts = [
            {
                "speaker": t.speaker,
                "text": t.text,
                "t_start": t.t_start,
                "t_end": t.t_end,
            }
            for t in turns
        ]
        dimension_scores = _aggregate(evals)
        evidence = [(e.dimension, e.score, e.evidence_span) for e in evals]
        coverage = session.coverage_map

    narrative = asyncio.run(_narrative(dimension_scores, evidence, coverage))

    with db() as s:
        existing = s.query(Report).filter(Report.session_id == session_id).one_or_none()
        report = existing or Report(session_id=session_id)
        report.narrative = narrative
        report.dimension_scores = dimension_scores
        report.delivery = metrics(turn_dicts)
        report.coverage = coverage
        report.prompt_version = prompts.version("report")
        s.add(report)

        session = s.get(Session, session_id)
        session.state = "reported"
        session.ended_at = session.ended_at or datetime.now(UTC)

    log.info("session %s reported: %s", session_id, dimension_scores)
    return session_id


async def _narrative(
    scores: dict, evidence: list[tuple[str, int, str]], coverage: dict | None
) -> str:
    if not scores:
        return "Not enough of the interview was scored to write a summary."

    lines = [f"{dim}: {v['score']} over {v['n']} answers" for dim, v in scores.items()]
    quotes = [f'{dim} scored {score} on: "{span}"' for dim, score, span in evidence[:12]]
    covered = [t["name"] for t in (coverage or {}).get("topics", []) if t["status"] != "unprobed"]

    user = (
        "Scores:\n" + "\n".join(lines) + "\n\n"
        "Evidence:\n" + "\n".join(quotes) + "\n\n"
        f"Topics covered: {', '.join(covered) or 'none recorded'}"
    )
    try:
        return await complete(get_llm(), prompts.load("report"), user, max_tokens=700)
    except Exception:
        log.exception("narrative failed; the report still has its scores")
        return ""
