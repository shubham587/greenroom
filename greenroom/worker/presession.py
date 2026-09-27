"""Resume and job description in, coverage map and problem out.

Nobody is waiting on a latency budget here, so every model call lives in this
file rather than in a request handler.
"""

from __future__ import annotations

import asyncio
import logging

from greenroom.db.models import Session
from greenroom.db.session import db
from greenroom.intake import build_coverage_map, extract_pdf, parse_jd, parse_resume
from greenroom.llm.client import get_llm
from greenroom.problems import select
from greenroom.worker.app import app

log = logging.getLogger(__name__)


async def _intake(resume_text: str, jd_text: str):
    llm = get_llm()
    # independent calls, so do not pay for them one after the other
    resume, jd = await asyncio.gather(parse_resume(llm, resume_text), parse_jd(llm, jd_text))
    return resume, jd, build_coverage_map(resume, jd)


@app.task(name="greenroom.worker.prepare_session", acks_late=True)
def prepare_session(session_id: str, resume_text: str, jd_text: str) -> str:
    """created -> parsing -> ready, or failed."""
    with db() as s:
        session = s.get(Session, session_id)
        if session:
            session.state = "parsing"

    try:
        resume, jd, coverage = asyncio.run(_intake(resume_text, jd_text))
        problem = select(jd)
    except Exception:
        log.exception("intake failed for %s", session_id)
        with db() as s:
            session = s.get(Session, session_id)
            if session:
                session.state = "failed"
        raise

    with db() as s:
        session = s.get(Session, session_id)
        session.resume_json = resume.model_dump()
        session.jd_json = jd.model_dump()
        session.coverage_map = coverage.model_dump()
        session.problem_id = problem.id if problem else None
        session.state = "ready"

    log.info(
        "session %s ready: %d topics, problem=%s",
        session_id,
        len(coverage.topics),
        problem.id if problem else None,
    )
    return session_id


__all__ = ["extract_pdf", "prepare_session"]
