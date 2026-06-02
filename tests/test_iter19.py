"""Tests for iter19: entropy detection, curator_apply audit, qdrant-client version."""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# iter19-A: entropy detection in privacy.py
# ---------------------------------------------------------------------------

class TestEntropyDetection:
    def test_high_entropy_token_redacted(self):
        from memorycore.privacy import redact_secrets
        # 32-char random base64-like string with no known prefix
        text = "secret=xK9mP2vQ8nL5rT1wZ6yA3bC7dE0fG4h"
        r = redact_secrets(text)
        assert "xK9mP2vQ8nL5rT1wZ6yA3bC7dE0fG4h" not in r.text
        assert r.redacted_count >= 1

    def test_bare_high_entropy_string_redacted(self):
        """A bare high-entropy token with no known prefix is caught by entropy pass."""
        from memorycore.privacy import redact_secrets, _shannon_entropy
        token = "aB3cD9eF2gH7iJ5kL1mN8oP4qR6sT0uV"  # 32 chars, high entropy
        assert _shannon_entropy(token) >= 4.0
        r = redact_secrets(token)
        assert "[REDACTED-HIGH-ENTROPY]" in r.text or r.redacted_count >= 1

    def test_low_entropy_string_not_redacted(self):
        from memorycore.privacy import redact_secrets
        text = "The user stored a preference for dark mode in the settings."
        r = redact_secrets(text)
        assert r.text == text
        assert r.redacted_count == 0

    def test_already_redacted_placeholder_not_double_redacted(self):
        from memorycore.privacy import redact_secrets
        text = "API_KEY=[REDACTED-API-KEY] and TOKEN=[REDACTED]"
        r = redact_secrets(text)
        assert "[REDACTED-HIGH-ENTROPY]" not in r.text
        assert r.text == text

    def test_entropy_label_present_when_fired(self):
        from memorycore.privacy import redact_secrets, _shannon_entropy
        token = "zY8xW7vU6tS5rQ4pO3nM2lK1jI0hG9fE"
        assert _shannon_entropy(token) >= 4.5
        r = redact_secrets(token)
        if r.redacted_count > 0:
            assert any(l in r.labels for l in ["high_entropy", "env_assignment", "openai_key", "github_token"])

    def test_short_token_not_flagged_by_entropy(self):
        from memorycore.privacy import redact_secrets
        text = "use code AB12CD34EF for login"
        r = redact_secrets(text)
        assert "AB12CD34EF" in r.text


# ---------------------------------------------------------------------------
# iter19-B: curator_apply audit event
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LMMCP_DB", str(tmp_path / "iter19_test.sqlite3"))
    from memorycore import models
    monkeypatch.setattr(models, "_INITIALIZED_DB_PATHS", set())
    return tmp_path


class TestCuratorApplyAudit:
    def test_curator_apply_dry_run_no_audit(self, isolated_db):
        from memorycore.storage import curator_report, get_audit_log
        curator_report(dry_run=True)
        rows = get_audit_log(event_type="curator_apply")
        assert len(rows) == 0

    def test_curator_apply_writes_audit_event(self, isolated_db):
        from memorycore.storage import add_memory_record, add_feedback, curator_report, get_audit_log
        rec = add_memory_record(
            memory_type="feedback",
            title="Obsolete tip",
            content="This advice is outdated and should be removed.",
        )
        for _ in range(5):
            add_feedback(rec["id"], -1.0, "not helpful")
        curator_report(dry_run=False)
        rows = get_audit_log(event_type="curator_apply")
        assert len(rows) == 1

    def test_curator_apply_audit_detail_fields(self, isolated_db):
        import json
        from memorycore.storage import curator_report, get_audit_log
        curator_report(dry_run=False)
        rows = get_audit_log(event_type="curator_apply")
        assert len(rows) == 1
        detail = json.loads(rows[0]["detail_json"])
        assert "stale" in detail
        assert "archived" in detail
        assert "total_actions" in detail


# ---------------------------------------------------------------------------
# iter19-C: qdrant-client version
# ---------------------------------------------------------------------------

class TestQdrantClientVersion:
    def test_qdrant_client_version_compatible(self):
        import importlib.metadata
        version = importlib.metadata.version("qdrant-client")
        major, minor, *_ = (int(x) for x in version.split("."))
        assert (major, minor) >= (1, 18), f"qdrant-client {version} is too old"
