"""The Celery app. Everything off the fast path runs here."""

from celery import Celery

from greenroom.config import settings

app = Celery("greenroom", broker=settings.redis_url, backend=settings.redis_url)

# acks_late everywhere: a worker dying mid-task hands the message back rather
# than losing the turn. Tasks are written to be idempotent for that reason.
app.conf.task_acks_late = True
app.conf.worker_prefetch_multiplier = 1
app.conf.task_default_queue = "scoring"
app.conf.task_routes = {
    "greenroom.worker.record_turn": {"queue": "scoring"},
    "greenroom.worker.score_turn": {"queue": "scoring"},
    "greenroom.worker.close_session": {"queue": "reports"},
}
app.conf.imports = ("greenroom.worker.tasks",)


@app.task(name="greenroom.worker.ping")
def ping() -> str:
    return "pong"
