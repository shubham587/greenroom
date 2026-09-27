"""Start a session from the command line, since there is no UI until phase 9.

    make session RESUME=path/to/cv.pdf JD=path/to/jd.txt

Prints the session id and waits for the worker to finish the intake, so the
thing you run next has something to attach to.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from greenroom.db.models import Session
from greenroom.db.session import db
from greenroom.intake import extract_pdf


def read(path: Path) -> str:
    data = path.read_bytes()
    return extract_pdf(data) if path.suffix.lower() == ".pdf" else data.decode("utf-8")


def main(resume_path: str, jd_path: str, timeout: int = 120) -> int:
    resume_text = read(Path(resume_path))
    jd_text = read(Path(jd_path))
    if not resume_text.strip():
        print(f"no text extracted from {resume_path} - is it a scanned image?")
        return 1

    with db() as s:
        session = Session(state="created")
        s.add(session)
        s.flush()
        session_id = session.id

    print(f"session {session_id}")
    print(f"  resume {len(resume_text)} chars, jd {len(jd_text)} chars")

    from greenroom.worker.presession import prepare_session

    prepare_session.delay(session_id, resume_text, jd_text)

    deadline = time.time() + timeout
    while time.time() < deadline:
        with db() as s:
            state = s.get(Session, session_id).state
        if state in {"ready", "failed"}:
            break
        print(f"  {state}...", end="\r", flush=True)
        time.sleep(1)

    with db() as s:
        session = s.get(Session, session_id)
        print(f"  state: {session.state}")
        if session.state != "ready":
            print("  (is `make worker` running?)")
            return 1

        topics = (session.coverage_map or {}).get("topics", [])
        print(f"  problem: {session.problem_id}")
        print(f"  coverage map: {len(topics)} topics")
        rank = {"high": 0, "medium": 1, "low": 2}
        for t in sorted(topics, key=lambda t: rank[t["priority"]])[:10]:
            print(f"    {t['priority']:<7} {t['name']:<24} ({t['source']}) {t['evidence'][:44]}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("usage: session.py <resume.pdf|txt> <jd.txt>")
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
