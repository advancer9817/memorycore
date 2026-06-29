from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import memorycore as lm
from memorycore.storage import add_memory_record, apply_governance_decision, create_governance_decision, reject_governance_decision
from memorycore.frontend import (
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
        Route("/api/{path:path}", frontend_api, methods=["GET", "POST", "PATCH", "PUT", "DELETE"]),
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


def test_curator_status_includes_llm_schedule_fields():
    with _client() as client:
        response = client.get("/api/curator/status?limit=5")

    data = response.json()["data"]
    assert response.status_code == 200
    assert "curator" in data
    assert "llm_curator" in data
    assert "timer" in data
    assert "schedules" in data
    assert "rule_curator" in data["schedules"]
    assert "llm_curator" in data["schedules"]


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


def test_frontend_v1_memory_compat_routes():
    with _client() as client:
        created = client.post("/api/v1/memories", json={
            "type": "project_memory",
            "title": "OpenMemory compat",
            "content": "lmmcp mcore local_memory compat API content",
            "atomize": False,
        })
        memory_id = created.json()["id"]
        listed = client.get("/api/v1/memories?query=lmmcp")
        filtered = client.post("/api/v1/memories/filter", json={"search_query": "mcore", "page": 1, "size": 5})
        detail = client.get(f"/api/v1/memories/{memory_id}")
        updated = client.put(f"/api/v1/memories/{memory_id}", json={"memory_content": "updated lmmcp mcore local_memory compat API content"})
        categories = client.get("/api/v1/memories/categories?user_id=test")
        entities = client.get("/api/v1/entities?query=local_memory")
        stats = client.get("/api/v1/stats")
        apps = client.get("/api/v1/apps/?sort_by=last_activity&sort_direction=desc&page_size=100")
        curator_status = client.get("/api/curator/status?limit=5")
        deleted = client.delete(f"/api/v1/memories/{memory_id}")

    assert created.status_code == 200
    assert listed.status_code == 200
    assert any(row["id"] == memory_id for row in listed.json()["items"])
    assert filtered.json()["total"] >= 1
    assert detail.json()["id"] == memory_id
    assert updated.json()["id"] == memory_id
    assert categories.status_code == 200
    assert isinstance(categories.json()["categories"], list)
    assert entities.status_code == 200
    assert any(hit["memory_id"] == memory_id for hit in entities.json())
    assert stats.json()["total_memories"] >= 1
    app = next(row for row in apps.json()["apps"] if row["id"] == "memorycore-ui")
    assert app["total_memories_created"] >= 1
    assert "last_activity_at" in app
    assert "status" in app
    assert curator_status.status_code == 200
    assert "stats" in curator_status.json()["data"]
    assert "curator" in curator_status.json()["data"]
    assert "llm_curator" in curator_status.json()["data"]
    assert "timer" in curator_status.json()["data"]
    assert "schedules" in curator_status.json()["data"]
    assert deleted.json()["status"] == "archived"


def test_frontend_apps_include_unknown_source_agent_with_stable_routes():
    source_agent = "memorycore-smoke-test"
    record = add_memory_record(
        "project_memory",
        "Smoke source agent",
        "memorycore smoke source agent route content",
        source_agent=source_agent,
    )

    with _client() as client:
        apps = client.get("/api/v1/apps/?page_size=100")
        detail = client.get(f"/api/v1/apps/{source_agent}")
        memories = client.get(f"/api/v1/apps/{source_agent}/memories?page=1&page_size=20")

    assert apps.status_code == 200
    app = next(row for row in apps.json()["apps"] if row["id"] == source_agent)
    assert app["name"] == source_agent
    assert app["total_memories_created"] >= 1
    assert detail.status_code == 200
    assert detail.json()["total_memories_created"] >= 1
    assert memories.status_code == 200
    assert any(item["id"] == record["id"] for item in memories.json()["memories"])


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


def test_frontend_governance_bad_request_includes_message():
    record = add_memory_record("episodic_memory", "Governance API note", "Can be split", importance=0.6)
    # Use split action which routes to needs_review, then reject it
    decision = create_governance_decision(
        "split_candidate",
        "split",
        [record["id"]],
        0.95,
        "high",
        {"id": record["id"], "action": "split", "sub_memories": []},
    )
    reject_governance_decision(decision["id"], source_agent="pytest", reason="reject before apply")

    with _client() as client:
        response = client.post(f"/api/governance/{decision['id']}/apply", json={"source_agent": "pytest"})

    payload = response.json()
    assert response.status_code == 400
    assert payload["ok"] is False
    assert payload["error"]["code"] == "bad_request"
    assert payload["error"]["message"] == "decision cannot be applied from status 'rejected'"


def test_frontend_governance_actionable_filter_excludes_applied_history():
    active = add_memory_record("episodic_memory", "Frontend active", "Actionable split", importance=0.3)
    applied = add_memory_record("episodic_memory", "Frontend applied", "Historical", importance=0.3)
    # Use split action which routes to needs_review (actionable)
    active_decision = create_governance_decision(
        "split_candidate",
        "split",
        [active["id"]],
        0.95,
        "high",
        {"id": active["id"], "action": "split", "sub_memories": []},
    )
    # downgrade with high confidence auto-applies immediately
    applied_decision = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [applied["id"]],
        0.95,
        "low",
        {"id": applied["id"], "action": "downgrade", "new_importance": 0.2},
    )

    with _client() as client:
        actionable = client.get("/api/governance/decisions?review_status=actionable")
        history = client.get("/api/governance/decisions?review_status=all")

    actionable_ids = {decision["id"] for decision in actionable.json()["data"]}
    history_ids = {decision["id"] for decision in history.json()["data"]}
    assert actionable.status_code == 200
    assert active_decision["id"] in actionable_ids
    assert applied_decision["id"] not in actionable_ids
    assert applied_decision["id"] in history_ids


def test_frontend_llm_curator_job_decisions_are_cursor_paginated(monkeypatch):
    from memorycore.storage.llm_curator_jobs import create_llm_curator_job

    first = add_memory_record("episodic_memory", "LLM incremental target", "Incremental job content", importance=0.4)
    second = add_memory_record("episodic_memory", "LLM incremental target 2", "Incremental job content 2", importance=0.4)
    job = create_llm_curator_job("job-test-incremental", params={"limit": 5}, created_by="pytest")
    first_decision = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [first["id"]],
        0.95,
        "low",
        {"id": first["id"], "action": "downgrade", "new_importance": 0.2, "reason": "incremental test 1"},
        curator_job_id=job["id"],
        curator_batch_id="batch-1",
    )
    second_decision = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [second["id"]],
        0.95,
        "low",
        {"id": second["id"], "action": "downgrade", "new_importance": 0.2, "reason": "incremental test 2"},
        curator_job_id=job["id"],
        curator_batch_id="batch-1",
    )

    with _client() as client:
        status = client.get(f"/api/curator/llm/{job['id']}")
        page = client.get(f"/api/curator/llm/{job['id']}/decisions?limit=1")
        next_cursor = page.json()["data"]["next_cursor"]
        next_page = client.get(f"/api/curator/llm/{job['id']}/decisions?limit=1&after={next_cursor}")

    assert status.status_code == 200
    assert status.json()["data"]["job_id"] == job["id"]
    assert page.status_code == 200
    first_id = page.json()["data"]["items"][0]["id"]
    second_id = next_page.json()["data"]["items"][0]["id"]
    assert {first_id, second_id} == {first_decision["id"], second_decision["id"]}
    assert page.json()["data"]["items"][0]["curator_job_id"] == job["id"]
    assert next_page.status_code == 200


def test_frontend_reject_applied_governance_decision_is_blocked():
    memory = add_memory_record("episodic_memory", "Reject applied target", "Reject applied content", importance=0.4)
    decision = create_governance_decision(
        "importance_reassessment",
        "downgrade",
        [memory["id"]],
        0.95,
        "low",
        {"id": memory["id"], "action": "downgrade", "new_importance": 0.2},
    )
    apply_governance_decision(decision["id"], source_agent="pytest")

    with _client() as client:
        rejected = client.post(f"/api/governance/{decision['id']}/reject", json={"source_agent": "pytest"})

    assert rejected.status_code == 400
    assert "cannot be rejected" in rejected.json()["error"]["message"]



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

    fake_module = types.ModuleType("memorycore.vector_store")
    fake_store = FakeVectorStore()
    fake_module.get_vector_store = lambda cfg: fake_store
    monkeypatch.setitem(sys.modules, "memorycore.vector_store", fake_module)

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
