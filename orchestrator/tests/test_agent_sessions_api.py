from fastapi.testclient import TestClient

from agents import auth_handler as auth_handler_module
from orchestrator.api.main import app


class FakeAuthHandler:
    sessions = []
    save_result = {}
    delete_result = False
    save_calls = []
    delete_calls = []

    def list_sessions(self):
        return self.sessions

    async def save_session(self, session_id, cookies, storage):
        self.save_calls.append(
            {
                "session_id": session_id,
                "cookies": cookies,
                "storage": storage,
            }
        )
        return self.save_result

    def delete_session(self, session_id):
        self.delete_calls.append(session_id)
        return self.delete_result


def _install_fake_auth_handler(monkeypatch, **attrs):
    fake = FakeAuthHandler()
    fake.sessions = attrs.get("sessions", [])
    fake.save_result = attrs.get("save_result", {})
    fake.delete_result = attrs.get("delete_result", False)
    fake.save_calls = []
    fake.delete_calls = []
    monkeypatch.setattr(auth_handler_module, "AuthHandler", lambda: fake)
    return fake


def test_list_agent_sessions_returns_auth_handler_sessions(monkeypatch):
    _install_fake_auth_handler(
        monkeypatch,
        sessions=[
            {
                "session_id": "signed-in",
                "created_at": "2026-06-16T10:00:00",
                "file": "/tmp/signed-in.json",
            }
        ],
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/agents/sessions")

    assert response.status_code == 200
    assert response.json() == {
        "sessions": [
            {
                "session_id": "signed-in",
                "created_at": "2026-06-16T10:00:00",
                "file": "/tmp/signed-in.json",
            }
        ]
    }


def test_create_agent_session_returns_auth_handler_success_payload(monkeypatch):
    fake = _install_fake_auth_handler(
        monkeypatch,
        save_result={
            "success": True,
            "session_id": "signed-in",
            "file": "/tmp/signed-in.json",
        },
    )
    payload = {
        "cookies": [{"name": "session", "value": "abc"}],
        "storage": {"token": "stored"},
    }

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/agents/sessions/signed-in", json=payload)

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "session_id": "signed-in",
        "file": "/tmp/signed-in.json",
    }
    assert fake.save_calls == [
        {
            "session_id": "signed-in",
            "cookies": [{"name": "session", "value": "abc"}],
            "storage": {"token": "stored"},
        }
    ]


def test_create_agent_session_failure_returns_400_with_error(monkeypatch):
    _install_fake_auth_handler(
        monkeypatch,
        save_result={
            "success": False,
            "error": "storage is not writable",
        },
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/agents/sessions/signed-in",
            json={"cookies": [], "storage": {}},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "storage is not writable"}


def test_delete_agent_session_returns_existing_success_payload(monkeypatch):
    fake = _install_fake_auth_handler(monkeypatch, delete_result=True)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.delete("/api/agents/sessions/signed-in")

    assert response.status_code == 200
    assert response.json() == {"status": "deleted", "session_id": "signed-in"}
    assert fake.delete_calls == ["signed-in"]


def test_delete_missing_agent_session_returns_404(monkeypatch):
    _install_fake_auth_handler(monkeypatch, delete_result=False)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.delete("/api/agents/sessions/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}


def test_agent_session_routes_registered_from_agent_sessions_router():
    endpoints = {
        (method, route.path): route.endpoint.__module__
        for route in app.routes
        if hasattr(route, "methods")
        for method in route.methods
    }

    assert endpoints[("GET", "/api/agents/sessions")] == "orchestrator.api.agent_sessions"
    assert endpoints[("POST", "/api/agents/sessions/{session_id}")] == "orchestrator.api.agent_sessions"
    assert endpoints[("DELETE", "/api/agents/sessions/{session_id}")] == "orchestrator.api.agent_sessions"
