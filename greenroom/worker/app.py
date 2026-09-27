"""The Celery app. Everything off the fast path runs here."""

from celery import Celery

from greenroom.config import settings

app = Celery("greenroom", broker=settings.redis_url, backend=settings.redis_url)
app.conf.task_acks_late = True
app.conf.task_routes = {
    "greenroom.worker.scoring.*": {"queue": "scoring"},
    "greenroom.worker.reports.*": {"queue": "reports"},
}


@app.task(name="greenroom.worker.ping")
def ping() -> str:
    return "pong"
