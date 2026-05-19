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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt (ported from mem0/configs/prompts.py — Apache-2.0)
# ---------------------------------------------------------------------------

ADDITIVE_EXTRACTION_PROMPT = """\
You are a Personal Information Organizer, specialized in accurately storing facts, \
user memories, and preferences. Your primary role is to extract relevant pieces of \
information from conversations and organize them into distinct, manageable facts.

# [IMPORTANT]: GENERATE FACTS SOLELY BASED ON THE USER'S MESSAGES. \
DO NOT INCLUDE INFORMATION FROM ASSISTANT OR SYSTEM MESSAGES.

Types of Information to Remember:
1. Personal Preferences: likes, dislikes, specific preferences.
2. Important Personal Details: names, relationships, important dates.
3. Plans and Intentions: upcoming events, goals, plans.
4. Professional Details: job titles, work habits, career goals.
5. Environment & Tools: OS, editors, languages, frameworks, workflows.
6. Decisions: choices made, approaches adopted, things rejected.
7. Miscellaneous: any other stable facts worth remembering.

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
    {"id": "0", "text": "...", "linked_memory_ids": ["<existing-uuid>"]},
    {"id": "1", "text": "..."}
  ]
}
linked_memory_ids is optional — include only when the new fact clearly relates to
an existing memory (same entity, update, contradiction, continuation).
"""


def _build_user_prompt(
    messages: list[dict[str, str]],
    existing_memories: list[dict[str, Any]],
    custom_instructions: str = "",
) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
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
                or ""
            )


def extraction_config_from_dict(cfg: dict[str, Any]) -> ExtractionConfig:
    """Build ExtractionConfig from config.yaml dict."""
    # Load .env if present
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    mem0 = cfg.get("mem0", {})
    extraction = cfg.get("extraction", {})
    # extraction section takes priority; fall back to mem0 section for compat
    return ExtractionConfig(
        api_key=extraction.get("api_key", "")
               or mem0.get("llm_api_key", "")
               or os.environ.get("MEM0_LLM_API_KEY", "")
               or os.environ.get("DEEPSEEK_API_KEY", ""),
        base_url=extraction.get("base_url",
                 mem0.get("llm_base_url", "https://api.deepseek.com/v1")),
        model=extraction.get("model",
              mem0.get("llm_model", "deepseek-v4-flash")),
        temperature=extraction.get("temperature",
                    mem0.get("temperature", 0.1)),
        max_tokens=extraction.get("max_tokens",
                   mem0.get("max_tokens", 2000)),
        timeout=extraction.get("timeout",
                mem0.get("timeout", 60)),
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


# ---------------------------------------------------------------------------
# Core extraction function
# ---------------------------------------------------------------------------

def extract_facts(
    messages: list[dict[str, str]],
    existing_memories: list[dict[str, Any]] | None = None,
    config: ExtractionConfig | None = None,
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

    today = datetime.now(timezone.utc).date().isoformat()
    system_prompt = ADDITIVE_EXTRACTION_PROMPT.replace("{today}", today)
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

    facts = _parse_response(raw)
    logger.info("extraction: extracted %d facts in %.2fs", len(facts), elapsed)
    return facts, elapsed


# ---------------------------------------------------------------------------
# LLM call (httpx, no SDK dependency)
# ---------------------------------------------------------------------------

def _call_llm(system_prompt: str, user_prompt: str, config: ExtractionConfig) -> str:
    """POST to OpenAI-compatible chat completions endpoint."""
    try:
        import httpx
    except ImportError:
        # httpx may not be installed; fall back to urllib
        return _call_llm_urllib(system_prompt, user_prompt, config)

    url = config.base_url.rstrip("/") + "/chat/completions"
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
    with httpx.Client(timeout=config.timeout) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


def _call_llm_urllib(
    system_prompt: str, user_prompt: str, config: ExtractionConfig
) -> str:
    """Fallback using stdlib urllib (no httpx)."""
    import urllib.request

    url = config.base_url.rstrip("/") + "/chat/completions"
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

def _parse_response(raw: str) -> list[ExtractedFact]:
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
            facts.append(ExtractedFact(
                text=text,
                linked_memory_ids=[str(x) for x in linked if x],
                raw_id=str(item.get("id", "")),
            ))

    return facts
