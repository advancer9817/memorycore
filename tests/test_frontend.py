from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import memorycore as lm
from memorycore.storage import add_memory_record, apply_governance_decision, create_governance_decision, reject_governance_decision
from memorycore.storage.db import managed_conn
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

    assert root.status_code == 404
    assert "8318" in root.text
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
            "content": "mcore memorycore compat API content",
            "atomize": False,
        })
        memory_id = created.json()["id"]
        listed = client.get("/api/v1/memories?query=memorycore")
        filtered = client.post("/api/v1/memories/filter", json={"search_query": "mcore", "page": 1, "size": 5})
        detail = client.get(f"/api/v1/memories/{memory_id}")
        updated = client.put(f"/api/v1/memories/{memory_id}", json={"memory_content": "updated mcore memorycore compat API content"})
        categories = client.get("/api/v1/memories/categories?user_id=test")
        entities = client.get("/api/v1/entities?query=memorycore")
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
    app = next(row for row in apps.json()["apps"] if row["id"] == "mcore")
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


def test_frontend_apps_alias_groups_and_curator_display_name():
    """A3 — hermes aliases collapse onto 'hermes'; llm_curator shows as 'llm-curator'."""
    add_memory_record(
        "project_memory", "Hermes default alias", "hermes-default alias content",
        source_agent="hermes-default",
    )
    add_memory_record(
        "project_memory", "Hermes router alias", "hermes-default-router alias content",
        source_agent="hermes-default-router",
    )
    add_memory_record(
        "project_memory", "LLM curator record", "llm curator content",
        source_agent="llm_curator",
    )
    add_memory_record(
        "project_memory", "Plain gemini record", "gemini content",
        source_agent="gemini",
    )

    with _client() as client:
        apps = client.get("/api/v1/apps/?page_size=100")

    rows = {row["id"]: row for row in apps.json()["apps"]}
    assert "hermes" in rows
    assert rows["hermes"]["total_memories_created"] >= 2  # both aliases grouped
    assert "hermes-default" not in rows
    assert "hermes-default-router" not in rows
    assert "mcore" in rows
    assert rows["mcore"]["total_memories_created"] >= 1
    assert "gemini" in rows  # identity display, still present
    # App detail resolves alias sources back to raw rows.
    detail = apps_detail("hermes")
    assert detail["total_memories_created"] >= 2

    # Verify update app management functionality (PUT /api/v1/apps/{app_id})
    with _client() as client:
        update_resp = client.put("/api/v1/apps/hermes", json={
            "display_name": "Hermes Pro Agent",
            "description": "Custom Hermes Description",
            "is_active": True,
        })
        assert update_resp.status_code == 200
        up_data = update_resp.json()
        assert up_data["display_name"] == "Hermes Pro Agent"
        assert up_data["description"] == "Custom Hermes Description"
        assert up_data["is_active"] is True


def apps_detail(app_id: str) -> dict:
    from memorycore.frontend_helpers import _app_details
    return _app_details(app_id)


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
    record = add_memory_record("episodic_memory", "Governance API note", "Can be downgraded", importance=0.6)
    # Create a promote decision (auto-applied), force to needs_review, then reject
    decision = create_governance_decision(
        "importance_reassessment",
        "promote",
        [record["id"]],
        0.95,
        "low",
        {"id": record["id"], "action": "promote", "new_importance": 0.8},
    )
    with managed_conn() as conn:
        conn.execute(
            "UPDATE governance_decisions SET review_status='needs_review', applied_at=NULL WHERE id=?",
            (decision["id"],),
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
    active = add_memory_record("episodic_memory", "Frontend active", "Actionable promote", importance=0.3)
    applied = add_memory_record("episodic_memory", "Frontend applied", "Historical", importance=0.3)
    # Create a promote decision (auto-applied), force to needs_review to make it actionable
    active_decision = create_governance_decision(
        "importance_reassessment",
        "promote",
        [active["id"]],
        0.95,
        "low",
        {"id": active["id"], "action": "promote", "new_importance": 0.5},
    )
    with managed_conn() as conn:
        conn.execute(
            "UPDATE governance_decisions SET review_status='needs_review', applied_at=NULL WHERE id=?",
            (active_decision["id"],),
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
        page = client.get(f"/api/curator/llm/{job['id']}/decisions?limit=1&review_status=all")
        next_cursor = page.json()["data"]["next_cursor"]
        next_page = client.get(f"/api/curator/llm/{job['id']}/decisions?limit=1&after={next_cursor}&review_status=all")

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


def test_delete_app_memories_syncs_vectors():
    """Archiving an app's memories must delete their Qdrant vectors (no stale leak)."""
    from unittest.mock import MagicMock, patch

    source_agent = "frontend-delete-sync-test"
    r1 = add_memory_record("project_memory", "App one", "first record", source_agent=source_agent, atomize=False)
    r2 = add_memory_record("project_memory", "App two", "second record", source_agent=source_agent, atomize=False)

    mock_vs = MagicMock()
    mock_vs.upsert.return_value = True
    mock_vs.delete.return_value = True

    with patch("memorycore.storage.crud._get_vector_store", return_value=mock_vs):
        with _client() as client:
            resp = client.delete(f"/api/v1/apps/{source_agent}")

    assert resp.status_code == 200
    assert resp.json()["archived_count"] == 2
    deleted_ids = {call.args[0] for call in mock_vs.delete.call_args_list}
    assert r1["id"] in deleted_ids
    assert r2["id"] in deleted_ids


def test_frontend_config_redacts_api_keys(monkeypatch, tmp_path):
    """The unauthenticated /api/v1/config endpoint must never leak full keys."""
    import json as _json

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "extraction:\n"
        "  api_key: sk-testsecret1234567890\n"
        "embedding:\n"
        "  api_key: emb-secret-abcdef\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCAL_MEMORY_CONFIG", str(cfg))
    from memorycore.models import invalidate_config_cache
    invalidate_config_cache()

    with _client() as client:
        config = client.get("/api/v1/config")

    data = config.json()
    assert data["llm"]["extraction"]["api_key"] == "sk-****7890"
    assert data["llm"]["embedding"]["api_key"] == "emb****cdef"
    assert "sk-testsecret1234567890" not in _json.dumps(config.json())


def test_frontend_config_write_ignores_masked_keys(monkeypatch, tmp_path):
    """A GET→PUT round-trip of the masked key must not overwrite the real key."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "extraction:\n"
        "  api_key: sk-testsecret1234567890\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCAL_MEMORY_CONFIG", str(cfg))
    from memorycore.models import invalidate_config_cache
    invalidate_config_cache()

    with _client() as client:
        client.put("/api/v1/config", json={"llm": {"extraction": {"api_key": "sk-****7890"}}})
        config = client.get("/api/v1/config")

    assert config.json()["llm"]["extraction"]["api_key"] == "sk-****7890"
    import yaml
    raw = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert raw["extraction"]["api_key"] == "sk-testsecret1234567890"


def test_frontend_v1_dashboard_health_and_legacy_fallback():
    """E1 Phase 1: /api/v1/dashboard aggregation + /api/v1/health-score +
    v1 fallback for curator/governance/graph (frontend now uses /v1 only)."""
    with _client() as client:
        dashboard = client.get("/api/v1/dashboard")
        health = client.get("/api/v1/health-score")
        curator_v1 = client.get("/api/v1/curator/status?limit=5")
        governance_v1 = client.get("/api/v1/governance/counts")
        graph_v1 = client.get("/api/v1/graph?limit=1")

    assert dashboard.status_code == 200
    payload = dashboard.json()
    assert "stats" in payload and "curator" in payload
    assert "governance" in payload and "apps" in payload
    assert "maintenance" in payload
    assert payload["total_memories"] >= 0

    assert health.status_code == 200
    health_payload = health.json()
    assert "quality" in health_payload and "risk" in health_payload
    assert "llmGovernance" in health_payload
    assert "metrics" in health_payload
    assert 0 <= float(health_payload["quality"]) <= 100
    assert 0 <= float(health_payload["risk"]) <= 100

    # v1 fallback routes (legacy handlers behind /api/v1/*) must answer.
    assert curator_v1.status_code == 200
    assert "stats" in curator_v1.json()  # v1 surface returns the bare payload (no `data` wrapper)
    assert governance_v1.status_code == 200
    assert graph_v1.status_code == 200


def test_frontend_v1_hooks_endpoints():
    """Verify lightweight HTTP hook endpoints for session-start, context, and stop."""
    with _client() as client:
        # 1. session-start
        res_start = client.post("/api/v1/hooks/session-start", json={})
        assert res_start.status_code == 200

        # 2. context with prompt
        res_ctx = client.post(
            "/api/v1/hooks/context",
            json={"prompt": "testing memory context injection", "agent": "claude"},
        )
        assert res_ctx.status_code == 200
        data = res_ctx.json()
        assert "hookSpecificOutput" in data
        assert data["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
        assert isinstance(data["hookSpecificOutput"]["additionalContext"], str)

        # 3. context with empty prompt
        res_empty = client.post("/api/v1/hooks/context", json={"prompt": ""})
        assert res_empty.status_code == 200
        empty_data = res_empty.json()
        assert empty_data["hookSpecificOutput"]["additionalContext"] == ""

        # 4. stop hook
        res_stop = client.post("/api/v1/hooks/stop", json={"agent": "claude"})
        assert res_stop.status_code == 200
        assert res_stop.json().get("status") == "ok"

