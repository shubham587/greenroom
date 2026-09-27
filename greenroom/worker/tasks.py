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

from greenroom.db.models import Evaluation, Session, Turn
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

    log.info("recorded %s turn %s", payload["speaker"], turn_id)

    # only a candidate's words are worth scoring
    if payload["speaker"] == "candidate":
        score_turn.delay(turn_id)
    return turn_id


@app.task(name="greenroom.worker.score_turn", acks_late=True, max_retries=3)
def score_turn(turn_id: str) -> str:
    """No-op until phase 7. Proves the queue hop and the write path.

    Phase 7 replaces the body: one schema-constrained call returning the
    evidence span first, then the score, then the upgraded answer.
    """
    with db() as s:
        turn = s.get(Turn, turn_id)
        if turn is None:
            log.warning("score_turn: no turn %s", turn_id)
            return turn_id

        s.add(
            Evaluation(
                turn_id=turn_id,
                dimension="placeholder",
                score=0,
                evidence_span=turn.text[:200],
                prompt_version=None,
            )
        )
    log.info("scored (no-op) turn %s", turn_id)
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
    return session_id
