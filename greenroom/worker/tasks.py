"""The slow loop.

Nothing here is on a latency budget. The agent fires `record_turn` and
forgets about it; by the time the interview ends most of the work behind the
report is already done.

`record_turn` is the only writer of turns, which is what keeps the agent out
of the database during a turn.
"""

from __future__ import annotations

import logging

from sqlalchemy.dialects.postgresql import insert as pg_insert

from greenroom.db.models import Decision, Evaluation, Session, Turn
from greenroom.db.session import db
from greenroom.worker.app import app

log = logging.getLogger(__name__)


def _ensure_session(s, session_id: str) -> None:
    """Create the session row if nobody has yet, without racing.

    Several turns of the same interview are handled concurrently, so a
    read-then-insert loses: every worker sees no session, every worker
    inserts, one wins and the rest raise UniqueViolation and drop their turn.
    ON CONFLICT DO NOTHING makes the check and the insert one statement.
    """
    s.execute(
        pg_insert(Session)
        .values(id=session_id, state="live")
        .on_conflict_do_nothing(index_elements=["id"])
    )


@app.task(name="greenroom.worker.record_turn", acks_late=True, max_retries=3)
def record_turn(payload: dict) -> str:
    """Persist one completed turn, then queue it for scoring.

    Idempotent on turn id, so a redelivered message cannot double-write - with
    acks_late a worker dying mid-task means the broker hands the same turn to
    someone else.
    """
    with db() as s:
        if payload.get("id") and s.get(Turn, payload["id"]):
            log.info("turn %s already recorded", payload["id"])
            return payload["id"]

        _ensure_session(s, payload["session_id"])

        turn = Turn(
            session_id=payload["session_id"],
            stage=payload.get("stage", "intro"),
            speaker=payload["speaker"],
            text=payload["text"],
            t_start=payload["t_start"],
            t_end=payload["t_end"],
            ttft_ms=payload.get("ttft_ms"),
            think_ms=payload.get("think_ms"),
            audio_url=payload.get("audio_url"),
        )
        if payload.get("id"):
            turn.id = payload["id"]
        s.add(turn)
        s.flush()
        turn_id = turn.id

        # the inspectable trace: why this question and not another one
        if payload.get("decision"):
            d = payload["decision"]
            s.add(
                Decision(
                    turn_id=turn_id,
                    route=d["route"],
                    reason=d["reason"],
                    topic=d.get("topic") or None,
                )
            )

        session = s.get(Session, payload["session_id"])
        if payload.get("coverage_map"):
            session.coverage_map = payload["coverage_map"]
        # which stage the interview reached, so another worker can resume it
        session.stage = payload.get("stage") or session.stage

    log.info("recorded %s turn %s", payload["speaker"], turn_id)

    # only a candidate's words are worth scoring
    if payload["speaker"] == "candidate":
        score_turn.delay(turn_id)
    return turn_id


@app.task(name="greenroom.worker.score_turn", acks_late=True, max_retries=3)
def score_turn(turn_id: str) -> str:
    """Score one candidate answer against the dimensions its stage can show.

    Idempotent: a redelivered message replaces this turn's evaluations rather
    than adding a second set, because acks_late means redelivery happens.
    """
    import asyncio

    from greenroom import prompts
    from greenroom.llm.client import get_llm
    from greenroom.scoring import score as score_answer

    with db() as s:
        turn = s.get(Turn, turn_id)
        if turn is None:
            log.warning("score_turn: no turn %s", turn_id)
            return turn_id
        if turn.speaker != "candidate":
            return turn_id

        # the question this was an answer to
        previous = (
            s.query(Turn)
            .filter(
                Turn.session_id == turn.session_id,
                Turn.speaker == "interviewer",
                Turn.t_start <= turn.t_start,
            )
            .order_by(Turn.t_start.desc())
            .first()
        )
        question = previous.text if previous else ""
        stage, answer = turn.stage, turn.text

    scores = asyncio.run(score_answer(get_llm(), stage, question, answer))

    with db() as s:
        s.query(Evaluation).filter(Evaluation.turn_id == turn_id).delete()
        for sc in scores:
            s.add(
                Evaluation(
                    turn_id=turn_id,
                    dimension=sc.dimension,
                    score=sc.score,
                    evidence_span=sc.evidence_span,
                    ideal_answer=sc.ideal_answer or None,
                    prompt_version=prompts.version("scorer"),
                )
            )

    log.info("scored turn %s: %s", turn_id, [(x.dimension, x.score) for x in scores])
    return turn_id


@app.task(name="greenroom.worker.close_session", acks_late=True)
def close_session(session_id: str, state: str = "completed") -> str:
    from datetime import UTC, datetime

    with db() as s:
        # the closing task can outrun the last turn, so do not assume the row
        _ensure_session(s, session_id)
        session = s.get(Session, session_id)
        session.state = state
        session.ended_at = datetime.now(UTC)
    log.info("session %s -> %s", session_id, state)

    # the report waits for the scoring backlog itself, so this can fire now
    if state == "completed":
        from greenroom.worker.reports import finalize_report

        finalize_report.delay(session_id)
    return session_id
