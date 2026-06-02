"""TDD tests for privacy.py — secret redaction at write time (P0-3)."""
from __future__ import annotations

import pytest
from memorycore.privacy import redact_secrets, redact_record_fields


class TestRedactSecrets:
    def test_openai_key_redacted(self):
        text = "Use sk-abcdefghijklmnopqrstuvwxyz1234 for auth"
        r = redact_secrets(text)
        assert "[REDACTED-API-KEY]" in r.text
        assert "sk-abcdefghijklmnopqrstuvwxyz1234" not in r.text
        assert r.redacted_count >= 1

    def test_anthropic_key_redacted(self):
        text = "token = sk-ant-api03-AAABBBCCCDDDEEEFFFGGGHHH"
        r = redact_secrets(text)
        assert "[REDACTED" in r.text
        assert "sk-ant-api03" not in r.text

    def test_github_token_redacted(self):
        # Bare token without assignment prefix — hits github_token pattern
        text = "Copy this token: ghp_abcdefghijklmnopqrst1234 and use it"
        r = redact_secrets(text)
        assert "[REDACTED-GITHUB-TOKEN]" in r.text
        assert "ghp_abcdefghijklmnopqrst1234" not in r.text

    def test_aws_access_key_redacted(self):
        text = "aws_access_key_id = AKIAIOSFODNN7EXAMPLE"
        r = redact_secrets(text)
        assert "[REDACTED-AWS-KEY]" in r.text
        assert "AKIAIOSFODNN7EXAMPLE" not in r.text

    def test_bearer_token_redacted(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        r = redact_secrets(text)
        assert "Bearer [REDACTED]" in r.text

    def test_connection_string_password_redacted(self):
        text = "db_url = postgres://admin:supersecretpass@db.example.com/mydb"
        r = redact_secrets(text)
        assert "supersecretpass" not in r.text
        assert "[REDACTED]" in r.text
        assert "postgres://admin:" in r.text  # prefix preserved

    def test_env_assignment_redacted(self):
        text = 'API_KEY="my-very-secret-key-1234"'
        r = redact_secrets(text)
        assert "my-very-secret-key-1234" not in r.text
        assert "[REDACTED]" in r.text

    def test_pem_private_key_redacted(self):
        text = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEA2a+FakeKeyData==\n"
            "-----END RSA PRIVATE KEY-----"
        )
        r = redact_secrets(text)
        assert "[REDACTED-PRIVATE-KEY]" in r.text
        assert "MIIEowIBAAKCAQEA" not in r.text

    def test_clean_text_unchanged(self):
        text = "This memory is about Python async patterns and event loops."
        r = redact_secrets(text)
        assert r.text == text
        assert r.redacted_count == 0
        assert r.labels == []

    def test_already_redacted_is_idempotent(self):
        text = "API_KEY=[REDACTED]"
        r = redact_secrets(text)
        assert r.text == text

    def test_labels_track_which_patterns_fired(self):
        text = "sk-abcdefghijklmnopqrstuvwxyz1234 and ghp_abcdefghijklmnopqrst1234"
        r = redact_secrets(text)
        assert "openai_key" in r.labels
        assert "github_token" in r.labels


class TestRedactRecordFields:
    def test_both_fields_redacted(self):
        title = "Config with TOKEN=abc12345678"
        content = "The API_KEY=secretvalue123 should not be stored."
        clean_title, clean_content, t_res, c_res = redact_record_fields(title, content)
        assert "abc12345678" not in clean_title
        assert "secretvalue123" not in clean_content
        assert t_res.redacted_count >= 1
        assert c_res.redacted_count >= 1

    def test_clean_fields_pass_through(self):
        title = "Debugging async event loop patterns"
        content = "Use asyncio.run() to run coroutines from synchronous code."
        clean_title, clean_content, t_res, c_res = redact_record_fields(title, content)
        assert clean_title == title
        assert clean_content == content
        assert t_res.redacted_count == 0
        assert c_res.redacted_count == 0


class TestAddMemoryRedaction:
    """Integration: verify redaction fires during actual storage write."""

    def test_secret_not_stored_in_db(self, tmp_path, monkeypatch):
        import os
        monkeypatch.setenv("LOCAL_MEMORY_DB", str(tmp_path / "test.sqlite3"))
        # Reset initialized DB cache so tmp DB is used
        from memorycore import models
        monkeypatch.setattr(models, "_INITIALIZED_DB_PATHS", set())
        from memorycore.storage import add_memory_record, get_record
        record = add_memory_record(
            memory_type="project_memory",
            title="Service credentials",
            content="API_KEY=supersecret99 use this to call the endpoint",
        )
        fetched = get_record(record["id"])
        assert "supersecret99" not in fetched["content"]
        assert "[REDACTED]" in fetched["content"]
