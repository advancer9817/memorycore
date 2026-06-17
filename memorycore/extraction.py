"""Memory extraction layer.

Calls DeepSeek (or any OpenAI-compatible LLM) with the ADDITIVE_EXTRACTION_PROMPT
to extract structured facts from conversations.  No mem0ai dependency.

Public API
----------
extract_facts(messages, existing_memories, config) -> list[ExtractedFact]
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memorycore.models import load_config, local_now

logger = logging.getLogger(__name__)


def _language_instruction(output_language: str) -> str:
    if output_language == "zh":
        return (
            "\n\n# Language Constraint\n"
            "You MUST output all memory content (title, content, tags) in Chinese (中文). "
            "Keep technical terms, proper nouns, version numbers untranslated. "
            "Output format remains JSON.\n"
        )
    if output_language == "en":
        return (
            "\n\n# Language Constraint\n"
            "You MUST output all memory content (title, content, tags) in English. "
            "Output format remains JSON.\n"
        )
    return ""


# ---------------------------------------------------------------------------
# Prompt (ported from mem0/configs/prompts.py — Apache-2.0)
# ---------------------------------------------------------------------------

ADDITIVE_EXTRACTION_PROMPT = """\
You are a Personal Information Organizer specialized in accurately storing facts, \
user memories, and preferences from developer/engineering conversations. \
Your primary role is to extract relevant pieces of information from conversations \
and organize them into distinct, manageable facts.

# [IMPORTANT]: ANALYZE THE FULL CONVERSATION (both user and assistant messages). \
Extract facts revealed by the USER's intent, decisions, and requests — \
but also extract technical facts confirmed in ASSISTANT responses: \
bug root causes, code changes made, fixes applied, architectural decisions, \
and project context. Do NOT extract filler, greetings, or generic assistant prose.

Types of Information to Remember:
1. Personal Preferences: likes, dislikes, specific preferences.
2. Important Personal Details: names, relationships, important dates.
3. Plans and Intentions: upcoming events, goals, plans.
4. Professional Details: job titles, work habits, career goals.
5. Environment & Tools: OS, editors, languages, frameworks, workflows.
6. Decisions: choices made, approaches adopted, things rejected.
7. Bug Fixes & Root Causes: what broke, why it broke, how it was fixed.
8. Code Changes: files modified, logic changed, new features added.
9. Miscellaneous: any other stable facts worth remembering.

Few-shot examples:
Input: Hi.
Output: {"memory": []}

Input: My name is Alice and I use Neovim with lazy.nvim.
Output: {"memory": [{"id": "0", "text": "User's name is Alice and uses Neovim with lazy.nvim plugin manager"}]}

Input: I switched from Python to Rust for performance-critical modules.
Output: {"memory": [{"id": "0", "text": "User switched from Python to Rust for performance-critical modules"}]}

Rules:
- Today's date is {today}.
- Detect the language of the user input and record facts in the same language.
- If nothing is worth extracting, return: {"memory": []}
- Each fact must be self-contained (replace pronouns with "User" or the person's name).
- Capture transitions: what changed AND what it changed from.
- Preserve specific details: exact names, versions, numbers, titles.
- Return ONLY valid JSON parseable by json.loads(). No prose, no markdown fences.

Output format:
{
  "memory": [
    {"id": "0", "text": "...", "importance": 0.7, "linked_memory_ids": ["<existing-uuid>"]},
    {"id": "1", "text": "...", "importance": 0.4}
  ]
}
linked_memory_ids is optional — include only when the new fact clearly relates to
an existing memory (same entity, update, contradiction, continuation).

importance is a float 0.0–1.0 rating how durable and reusable this fact is:
  0.8–1.0: identity, long-term preferences, decisions, environment facts
  0.5–0.7: project context, tools, workflows, plans
  0.2–0.4: ephemeral context, transient debugging details, one-off mentions
  0.0–0.1: greetings, filler, chat noise — DO NOT extract these
Only extract facts with importance >= 0.3. Skip trivial or transient information.
"""


def _build_user_prompt(
    messages: list[dict[str, str]],
    existing_memories: list[dict[str, Any]],
    custom_instructions: str = "",
) -> str:
    today = local_now().date().isoformat()
    parts: list[str] = []

    parts.append(f"## Observation Date\n{today}")

    if existing_memories:
        mem_list = [{"id": m["id"], "text": m.get("content", m.get("text", ""))}
                    for m in existing_memories]
        parts.append(f"## Existing Memories\n{json.dumps(mem_list, ensure_ascii=False)}")
    else:
        parts.append("## Existing Memories\n[]")

    parts.append(f"## New Messages\n{json.dumps(messages, ensure_ascii=False)}")

    if custom_instructions:
        parts.append(f"## Custom Instructions\n{custom_instructions}")

    parts.append("# Output:")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class ExtractionConfig:
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-v4-flash"
    temperature: float = 0.1
    max_tokens: int = 2000
    timeout: int = 60
    custom_instructions: str = ""

    def __post_init__(self):
        # Resolve API key from env if not set
        if not self.api_key:
            self.api_key = (
                os.environ.get("MEM0_LLM_API_KEY")
                or os.environ.get("DEEPSEEK_API_KEY")
                or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                or ""
            )


def extraction_config_from_dict(cfg: dict[str, Any]) -> ExtractionConfig:
    """Build ExtractionConfig from config.yaml dict.

    API keys are resolved from: config dict > environment variables.
    Set DEEPSEEK_API_KEY or MEM0_LLM_API_KEY in your environment.
    """
    extraction = cfg.get("extraction", {})
    return ExtractionConfig(
        api_key=extraction.get("api_key", "")
               or os.environ.get("MEM0_LLM_API_KEY", "")
               or os.environ.get("DEEPSEEK_API_KEY", ""),
        base_url=extraction.get("base_url", "https://api.deepseek.com/v1"),
        model=extraction.get("model", "deepseek-v4-flash"),
        temperature=extraction.get("temperature", 0.1),
        max_tokens=extraction.get("max_tokens", 16000),
        timeout=extraction.get("timeout", 60),
        custom_instructions=extraction.get("custom_instructions", ""),
    )


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ExtractedFact:
    text: str
    linked_memory_ids: list[str] = field(default_factory=list)
    raw_id: str = ""          # sequential id from LLM response ("0", "1", ...)
    importance: float = 0.5   # LLM-assigned importance 0.0–1.0


# ---------------------------------------------------------------------------
# Core extraction function
# ---------------------------------------------------------------------------

def extract_facts(
    messages: list[dict[str, str]],
    existing_memories: list[dict[str, Any]] | None = None,
    config: ExtractionConfig | None = None,
    *,
    min_importance: float = 0.3,
    chinese_detection_ratio: float = 0.15,
) -> tuple[list[ExtractedFact], float]:
    """Extract facts from a conversation using an LLM.

    Parameters
    ----------
    messages:
        Conversation turns: [{"role": "user"|"assistant", "content": "..."}]
    existing_memories:
        Already-stored memories to help the LLM detect duplicates/links.
        Each item needs at least {"id": str, "content"|"text": str}.
    config:
        ExtractionConfig.  Uses module-level default if None.

    Returns
    -------
    (facts, elapsed_seconds)
        facts: list of ExtractedFact (may be empty)
        elapsed_seconds: wall-clock time for the LLM call
    """
    if config is None:
        config = ExtractionConfig()

    if not config.api_key:
        logger.warning("extraction: no API key configured — skipping LLM call")
        return [], 0.0

    today = local_now().date().isoformat()
    system_prompt = ADDITIVE_EXTRACTION_PROMPT.replace("{today}", today)

    output_language = load_config().get("output_language", "auto")
    lang_suffix = _language_instruction(output_language)
    if lang_suffix:
        system_prompt += lang_suffix
    elif output_language == "auto":
        all_text = " ".join(m.get("content", "") for m in messages)
        chinese_chars = sum(1 for c in all_text if "一" <= c <= "鿿")
        if len(all_text) > 0 and chinese_chars / max(len(all_text), 1) > chinese_detection_ratio:
            system_prompt += (
                "\n\n# 中文补充说明\n"
                "- 当输入消息主要为中文时，请用中文记录所有事实。\n"
                "- 标题和内容均使用中文，保持具体细节（版本号、人名、工具名等）不翻译。\n"
                "- 输出格式不变，仍为 JSON。\n"
            )
    user_prompt = _build_user_prompt(
        messages,
        existing_memories or [],
        config.custom_instructions,
    )

    t0 = time.time()
    try:
        raw = _call_llm(system_prompt, user_prompt, config)
    except Exception as exc:
        elapsed = time.time() - t0
        logger.error("extraction: LLM call failed: %s", exc)
        return [], elapsed

    elapsed = time.time() - t0

    facts = _parse_response(raw, min_importance=min_importance)
    logger.info("extraction: extracted %d facts in %.2fs", len(facts), elapsed)
    return facts, elapsed

# ---------------------------------------------------------------------------
# LLM call (httpx, no SDK dependency)
# ---------------------------------------------------------------------------

# Module-level connection pool — avoids TCP handshake overhead on repeated calls.
_httpx_client: "httpx.Client | None" = None
_httpx_client_key: tuple = ()


def _get_httpx_client(config: "ExtractionConfig") -> "httpx.Client":
    global _httpx_client, _httpx_client_key
    import httpx
    key = (config.base_url, config.timeout)
    if _httpx_client is None or _httpx_client_key != key:
        if _httpx_client is not None:
            try:
                _httpx_client.close()
            except Exception:
                pass
        _httpx_client = httpx.Client(timeout=config.timeout, limits=httpx.Limits(max_keepalive_connections=4, max_connections=8))
        _httpx_client_key = key
    return _httpx_client


def _call_llm(system_prompt: str, user_prompt: str, config: ExtractionConfig) -> str:
    """POST to OpenAI-compatible chat completions endpoint."""
    try:
        import httpx
    except ImportError:
        return _call_llm_urllib(system_prompt, user_prompt, config)

    base = config.base_url.rstrip("/")
    # Auto-add /v1 prefix if the base URL doesn't end with /v1 or /v1/...
    # This handles proxies like CPA that expose /v1/chat/completions
    if not (base.endswith("/v1") or "/v1/" in base.split("://", 1)[-1]):
        url = base + "/v1/chat/completions"
    else:
        url = base + "/chat/completions"
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    client = _get_httpx_client(config)
    resp = client.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    msg = data["choices"][0]["message"]
    # Claude models return reasoning in reasoning_content; content is the JSON answer
    return msg.get("content") or msg.get("reasoning_content") or ""


def _call_llm_urllib(
    system_prompt: str, user_prompt: str, config: ExtractionConfig
) -> str:
    """Fallback using stdlib urllib (no httpx)."""
    import urllib.request

    base = config.base_url.rstrip("/")
    if not (base.endswith("/v1") or "/v1/" in base.split("://", 1)[-1]):
        url = base + "/v1/chat/completions"
    else:
        url = base + "/chat/completions"
    payload = json.dumps({
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=config.timeout) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def _parse_response(raw: str, *, min_importance: float = 0.3) -> list[ExtractedFact]:
    """Parse LLM JSON response into ExtractedFact list."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON substring
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                data = json.loads(raw[start:end])
            except json.JSONDecodeError:
                logger.warning("extraction: could not parse LLM response: %s", raw[:200])
                return []
        else:
            logger.warning("extraction: no JSON found in response: %s", raw[:200])
            return []

    memory_list = data.get("memory", data.get("facts", []))
    if not isinstance(memory_list, list):
        return []

    facts: list[ExtractedFact] = []
    for item in memory_list:
        if isinstance(item, str):
            # Older FACT_RETRIEVAL_PROMPT format: {"facts": ["..."]}
            text = item.strip()
            if text:
                facts.append(ExtractedFact(text=text))
        elif isinstance(item, dict):
            text = item.get("text", "").strip()
            if not text:
                continue
            linked = item.get("linked_memory_ids", [])
            if isinstance(linked, str):
                linked = [linked]
            imp = item.get("importance", 0.5)
            try:
                imp = max(0.0, min(1.0, float(imp)))
            except (TypeError, ValueError):
                imp = 0.5
            if imp < min_importance:
                continue
            facts.append(ExtractedFact(
                text=text,
                linked_memory_ids=[str(x) for x in linked if x],
                raw_id=str(item.get("id", "")),
                importance=imp,
            ))

    return facts
