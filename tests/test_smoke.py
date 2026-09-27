from fastapi.testclient import TestClient

from greenroom.api import app
from greenroom.config import settings


def test_settings_load():
    assert settings.database_url.startswith("postgresql")
    assert settings.redis_url.startswith("redis://")


def test_health():
    assert TestClient(app).get("/health").json() == {"status": "ok"}
