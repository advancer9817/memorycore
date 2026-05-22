"""Secret-redaction layer for memory writes.

Called at write-time (add_memory_record, update_memory_content) to strip
credentials, tokens, and other high-entropy secrets before they are stored.

Design choices:
- Pattern-based, not ML-based: deterministic, fast, no external calls.
- Redact, don't reject: replace the secret with a placeholder so the
  semantic meaning of the surrounding text is preserved.
- Idempotent: redacting already-redacted text is a no-op.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------
# Each entry: (label, compiled_pattern, replacement_template)
_REDACT_DEFS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    # OpenAI / Anthropic-style bearer tokens  sk-…  sk-ant-…  (specific first)
    (
        "openai_key",
        re.compile(r'\bsk-(?:ant-)?[A-Za-z0-9\-_]{20,}'),
        "[REDACTED-API-KEY]",
    ),
    # GitHub personal-access tokens  ghp_…  github_pat_…
    (
        "github_token",
        re.compile(r'\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9]{20,}'),
        "[REDACTED-GITHUB-TOKEN]",
    ),
    # AWS access key IDs  AKIA…
    (
        "aws_access_key",
        re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
        "[REDACTED-AWS-KEY]",
    ),
    # AWS secret access keys (40-char base64-like after keyword)
    (
        "aws_secret",
        re.compile(
            r'(?i)(aws[_-]secret[_-]access[_-]key\s*[:=]\s*)["\']?([A-Za-z0-9+/]{40})["\']?',
        ),
        r"\1[REDACTED]",
    ),
    # Bearer / Authorization header values
    (
        "bearer_token",
        re.compile(r'(?i)\bBearer\s+([A-Za-z0-9\-._~+/]+=*)\b'),
        "Bearer [REDACTED]",
    ),
    # Private-key PEM blocks
    (
        "pem_private_key",
        re.compile(
            r'-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',
            re.M,
        ),
        "[REDACTED-PRIVATE-KEY]",
    ),
    # Connection strings with embedded passwords  postgres://user:pass@host
    (
        "connection_string",
        re.compile(r'(?i)(\w+://[^:@\s]+:)([^@\s]+)(@)'),
        r"\1[REDACTED]\3",
    ),
    # Generic key=value assignments — last, so specific patterns above match first
    (
        "env_assignment",
        re.compile(
            r'(?i)((?:api[_-]?key|secret|token|password|passwd|pwd|credential|auth)'
            r'[_A-Z0-9]*\s*[:=]\s*)["\']?([A-Za-z0-9+/\-_.]{8,})["\']?',
        ),
        r"\1[REDACTED]",
    ),
)


@dataclass
class RedactionResult:
    text: str
    redacted_count: int = 0
    labels: list[str] = field(default_factory=list)


def redact_secrets(text: str) -> RedactionResult:
    """Scan *text* and replace known secret patterns with placeholders.

    Returns the cleaned text plus a count and list of pattern labels that fired.
    """
    result = text
    count = 0
    labels: list[str] = []
    for label, pattern, replacement in _REDACT_DEFS:
        new, n = pattern.subn(replacement, result)
        if n:
            result = new
            count += n
            labels.append(label)
    return RedactionResult(text=result, redacted_count=count, labels=labels)


def redact_record_fields(title: str, content: str) -> tuple[str, str, RedactionResult, RedactionResult]:
    """Redact both title and content, returning cleaned values and audit results."""
    t_result = redact_secrets(title)
    c_result = redact_secrets(content)
    return t_result.text, c_result.text, t_result, c_result
