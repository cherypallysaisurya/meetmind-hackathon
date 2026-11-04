import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app
from tests.fakes import InMemoryStore


@pytest.fixture(autouse=True)
def memory_store(monkeypatch):
    store = InMemoryStore()
    monkeypatch.setattr(main, "store", store)
    return store


def test_health_reports_the_auth_mode_and_where_the_language_model_runs():
    from app.config import settings
    assert TestClient(app).get("/api/health").json() == {"status": "ok", "mode": "local", "llm": settings.llm_provider,
                                                         "answerModel": settings.llm_answer_model}


def test_profile_is_missing_then_saved_then_loaded():
    client = TestClient(app)
    assert client.get("/api/profile").status_code == 404

    body = {"displayName": "Surya", "aliases": ["Sur"], "role": "Junior ML Engineer",
            "topics": ["retrieval"], "bio": "Works on retrieval.", "currentProjects": "MeetMind"}
    saved = client.put("/api/profile", json=body)
    assert saved.status_code == 200
    assert saved.json() == body
    assert client.get("/api/profile").json() == body


def test_profile_limits_are_enforced():
    client = TestClient(app)
    assert client.put("/api/profile", json={"displayName": ""}).status_code == 422
    assert client.put("/api/profile", json={"displayName": "S", "bio": "x" * 2001}).status_code == 422
