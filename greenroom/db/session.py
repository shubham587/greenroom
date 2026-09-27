"""One engine, one session factory, synchronous.

Sync on purpose. Celery workers are sync, and the agent deliberately never
touches the database inside a turn - it publishes to the queue and moves on -
so nothing in the fast loop is waiting on this. A second async stack would buy
nothing and cost two of everything.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from greenroom.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def db() -> Iterator[OrmSession]:
    """A transaction. Commits on success, rolls back on anything else."""
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
