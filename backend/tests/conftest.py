import os
import tempfile

os.environ["ADBOT_API_KEYS"] = "test-owner-key-000000000000000000000000,test-other-key-000000000000000000000000"
os.environ["ADBOT_DATABASE_URL"] = os.environ.get("ADBOT_TEST_DATABASE_URL") or "sqlite:///" + str(
    __import__("pathlib").Path(tempfile.mkdtemp(prefix="adbot-test-")) / "test.db"
)
os.environ["ADBOT_REDIS_URL"] = os.environ.get("ADBOT_TEST_REDIS_URL", "")
os.environ["ADBOT_ENVIRONMENT"] = "development"
os.environ["ADBOT_AI_PROVIDER"] = "disabled"
os.environ["ADBOT_AI_FALLBACK_PROVIDER"] = "disabled"
os.environ["ADBOT_BROWSER_SESSION_PERSISTENCE"] = "false"
os.environ["ADBOT_AUTHORIZED_DOMAINS"] = ""
os.environ["ADBOT_FIXTURE_MODE"] = "true"
os.environ["ADBOT_RATE_PER_MINUTE"] = "10000"
os.environ["ADBOT_ARTIFACT_DIR"] = tempfile.mkdtemp(prefix="adbot-artifacts-")

import pytest
from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app, rate_windows

KEY = os.environ["ADBOT_API_KEYS"].split(",")[0]
OTHER_KEY = os.environ["ADBOT_API_KEYS"].split(",")[1]
AUTH = {"Authorization": "Bearer " + KEY}
OTHER_AUTH = {"Authorization": "Bearer " + OTHER_KEY}


@pytest.fixture(autouse=True)
def database():
    from app.user_agents import invalidate
    invalidate()
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)
    rate_windows.clear()


@pytest.fixture
def client():
    with TestClient(app) as client:
        client.headers.update(AUTH)
        yield client


@pytest.fixture
def target(client):
    result = client.post(
        "/api/websites",
        json={
            "name": "Fixture",
            "base_url": "http://127.0.0.1:8765/",
            "allowed_domains": ["127.0.0.1"],
            "authorized": True,
            "configuration": {
                "max_pages": 10,
                "max_depth": 2,
                "delay_seconds": 0.1,
                "max_duration_seconds": 20,
                "screenshots": True,
            },
        },
    )
    assert result.status_code == 201, result.text
    return result.json()
