from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import local_memory_mcp as lm
from local_memory_mcp.frontend import (
    configure_frontend,
    frontend_api,
    frontend_health,
    frontend_index,
    validate_frontend_bind,
)


def _client(token: str = "") -> TestClient:
    configure_frontend(host="127.0.0.1", port=8318, auth_token=token, enabled=True)
    app = Starlette(routes=[
        Route("/", frontend_index, methods=["GET"]),
        Route("/health", frontend_health, methods=["GET"]),
        Route("/api/{path:path}", frontend_api, methods=["GET", "POST", "PATCH"]),
    ])
    return TestClient(app)


def test_frontend_root_and_health():
    with _client() as client:
        root = client.get("/")
        health = client.get("/health")

    assert root.status_code == 200
    assert "Local Memory MCP Control" in root.text
    assert health.status_code == 200
    assert health.json()["data"]["status"] == "ok"


def test_frontend_dashboard_payload_contains_ops_keys():
    lm.add_memory_record("project_memory", "Frontend", "Control service", memory_id="front-1")

    with _client() as client:
        response = client.get("/api/dashboard")

    data = response.json()["data"]
    assert response.status_code == 200
    assert data["rows"][0]["id"] == "front-1"
    assert "report" in data
    assert "links" in data
    assert "mailbox" in data
    assert "presence" in data
    assert "context_quality" in data


def test_frontend_memory_create_get_and_patch():
    with _client() as client:
        created = client.post("/api/memories", json={
            "type": "project_memory",
            "title": "Created from UI",
            "content": "Frontend content",
            "source_agent": "frontend-test",
        })
        memory_id = created.json()["data"]["id"]
        fetched = client.get(f"/api/memories/{memory_id}")
        updated = client.patch(f"/api/memories/{memory_id}", json={"title": "Updated from UI"})

    assert created.status_code == 200
    assert fetched.json()["data"]["title"] == "Created from UI"
    assert updated.json()["data"]["title"] == "Updated from UI"


def test_frontend_invalid_json_returns_400():
    with _client() as client:
        response = client.post("/api/memories", data="{bad", headers={"content-type": "application/json"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_json"


def test_frontend_missing_memory_returns_404():
    with _client() as client:
        response = client.get("/api/memories/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_frontend_auth_token_required_for_api():
    with _client(token="secret") as client:
        denied = client.get("/api/dashboard")
        allowed = client.get("/api/dashboard", headers={"Authorization": "Bearer secret"})

    assert denied.status_code == 401
    assert allowed.status_code == 200


def test_frontend_remote_bind_requires_token_or_explicit_insecure():
    try:
        validate_frontend_bind("0.0.0.0")
    except ValueError as exc:
        assert "requires" in str(exc)
    else:
        raise AssertionError("remote bind without token should fail")

    validate_frontend_bind("0.0.0.0", auth_token="secret")
    validate_frontend_bind("0.0.0.0", allow_insecure_remote=True)


def test_frontend_vector_search_passes_score_threshold_as_keyword(monkeypatch):
    calls = []

    class FakeVectorStore:
        def search(self, text, top_k=10, filters=None, score_threshold=0.0):
            calls.append({
                "text": text,
                "top_k": top_k,
                "filters": filters,
                "score_threshold": score_threshold,
            })
            return [
                SimpleNamespace(
                    id="vector-hit",
                    score=0.81234,
                    text=text,
                    payload={"source": "fake"},
                )
            ]

    fake_module = types.ModuleType("local_memory_mcp.vector_store")
    fake_store = FakeVectorStore()
    fake_module.get_vector_store = lambda cfg: fake_store
    monkeypatch.setitem(sys.modules, "local_memory_mcp.vector_store", fake_module)

    with _client() as client:
        response = client.get("/api/vector/search?query=semantic&top_k=3&score_threshold=0.72")

    assert response.status_code == 200
    assert response.json()["data"][0]["score"] == 0.8123
    assert calls == [{
        "text": "semantic",
        "top_k": 3,
        "filters": None,
        "score_threshold": 0.72,
    }]
