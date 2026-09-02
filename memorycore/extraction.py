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
import re
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
你是一个精准的工程对话事实提取器。
你的任务是从开发者与 AI 助手的对话中提取所有值得长期记住的事实。
提取的事实将在未来对话中作为上下文注入，帮助助手快速理解项目状态和用户偏好。

# 分析范围

分析完整对话（用户和助手的消息）。提取：
- 用户的意图、决策、请求中揭示的事实
- 助手回复中确认的技术事实：Bug 根因、代码变更、修复方案、架构决策
不提取：寒暄、感谢、进度更新、助手的通用解释

# 提取原则

1. 提取结果而非过程："通过修改 config.yaml 的 timeout 从 1.8s 改为 2.5s 解决了 hook 超时" > "用户问了 hook 超时的问题"
2. 自包含：每条事实脱离原对话后仍可独立理解，用具体名称替代代词
3. 保留细节：文件路径、配置值、版本号、端口号、命令参数
4. 捕获变化：记录"从X改为Y"而非只记录最终状态
5. 面向未来：问自己"下次对话时这条信息是否有用？"
6. 原子化：每条事实只表达一个独立结论；复杂决策拆为决策、原因、影响等多条事实
7. 标题完整：title 是不超过 80 字符的语义摘要，不得直接截取 content 开头
8. 内容紧凑：content 通常控制在 50-300 字符，保留使事实自包含所需的具体细节

# 输出格式

{{
  "memory": [
    {{
      "id": "0",
      "title": "...",
      "content": "...",
      "type": "decision",
      "importance": 0.8,
      "linked_memory_ids": ["<existing-uuid>"]
    }}
  ]
}}

## type 必须是以下之一：
- decision: 技术决策、选择的方案、放弃的方案及原因
- environment_fact: 环境配置、路径、端口、版本、依赖关系
- bug_fix: Bug 根因分析、修复方案、涉及的文件
- user_profile: 用户偏好、工作习惯、技术栈、角色
- project_memory: 项目状态、架构变更、里程碑、进度
- feedback: 用户对 AI 行为的纠正或确认（"不要这样做"、"就这样"）
- skill_learned: 可复用的工作流程、模式、技巧

## importance 评分：
  0.8–1.0: 根因分析、架构决策、用户强偏好、环境关键配置
  0.5–0.7: Bug 修复细节、配置变更、工作流决策、项目上下文
  0.3–0.4: 已完成任务的实现细节（短期有用）
  < 0.3: 不提取

## linked_memory_ids（可选）：
当新事实明确更新、矛盾或延续某条 Existing Memory 时填写其 id。

# 正确提取示例

Input: user: "mcore-context.sh 的 curl 超时 1.8s 太短了" / assistant: "根因是 Qdrant 向量查询偶发超过 1.5s，建议改为 2.5s" / user: "改了，同时 token_budget 从 1500 改到 2000"
Output: {{"memory": [
  {{"id": "0", "title": "mcore context hook 超时修复", "content": "mcore-context.sh 的 MCP 调用超时从 1.8s 改为 2.5s，根因是 Qdrant 向量查询偶发超过 1.5s", "type": "bug_fix", "importance": 0.7}},
  {{"id": "1", "title": "mcore context token budget 调整", "content": "mcore-context.sh 的 token_budget 从 1500 改为 2000", "type": "environment_fact", "importance": 0.6}}
]}}

Input: user: "不要在 PR 描述里加 emoji" / assistant: "好的，以后不加了"
Output: {{"memory": [{{"id": "0", "title": "PR 描述不使用 emoji", "content": "用户偏好：PR 描述中不使用 emoji", "type": "feedback", "importance": 0.8}}]}}

Input: user: "决定用 SQLite 而不是 PostgreSQL，因为本项目是单机部署" / assistant: "合理的选择"
Output: {{"memory": [{{"id": "0", "title": "项目数据库选择 SQLite", "content": "项目选择 SQLite 而非 PostgreSQL 作为数据库，原因是单机部署场景", "type": "decision", "importance": 0.9}}]}}

Input: user: "Hi" / assistant: "你好，有什么可以帮你的？"
Output: {{"memory": []}}

Input: user: "已完成第 3 步" / assistant: "好的，继续第 4 步"
Output: {{"memory": []}}

# 规则

- 今天日期是 {today}。
- 检测输入语言，用相同语言记录事实。中文输入用中文，英文输入用英文。
- 技术术语、专有名词、版本号保持原文不翻译。
- 无值得提取的内容时返回：{{"memory": []}}
- 仅返回合法 JSON，不要 prose，不要 markdown fence。
- importance < 0.3 的事实不要输出。
"""


def _build_user_prompt(
    messages: list[dict[str, str]],
    existing_memories: list[dict[str, Any]],
    custom_instructions: str = "",
    active_context: str = "",
) -> str:
    today = local_now().date().isoformat()
    parts: list[str] = []

    parts.append(f"## Observation Date\n{today}")

    if active_context:
        parts.append(active_context)

    if existing_memories:
        mem_list = [
            {
                "id": m["id"],
                "text": m.get("content", m.get("text", "")),
                "type": m.get("type", ""),
                "importance": m.get("importance", 0.5),
                "date": (m.get("created_at") or "")[:10],
            }
            for m in existing_memories
        ]
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
    timeout: int = 180
    custom_instructions: str = ""

    def __post_init__(self):
        # Resolve API key from env if not set
        if not self.api_key:
            self.api_key = (
                os.environ.get("LOCAL_MEMORY_LLM_API_KEY")
                or os.environ.get("MEM0_LLM_API_KEY")
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
               or os.environ.get("LOCAL_MEMORY_LLM_API_KEY", "")
               or os.environ.get("MEM0_LLM_API_KEY", "")
               or os.environ.get("DEEPSEEK_API_KEY", ""),
        base_url=extraction.get("base_url", "https://api.deepseek.com/v1"),
        model=extraction.get("model", "deepseek-v4-flash"),
        temperature=extraction.get("temperature", 0.1),
        max_tokens=extraction.get("max_tokens", 16000),
        timeout=extraction.get("timeout", 180),
        custom_instructions=extraction.get("custom_instructions", ""),
    )


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ExtractedFact:
    text: str
    title: str = ""
    linked_memory_ids: list[str] = field(default_factory=list)
    raw_id: str = ""          # sequential id from LLM response ("0", "1", ...)
    importance: float = 0.5   # LLM-assigned importance 0.0–1.0
    memory_type: str = ""     # LLM-assigned type (decision, bug_fix, etc.)
    subject: str = ""         # LLM-assigned canonical project name (optional)
    entities: list[str] = field(default_factory=list)  # LLM-assigned entities (optional)


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
    project_path: str = "",
    project_name: str = "",
    scope: str = "global",
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

    # Subject context (P1): tell the LLM which project this conversation belongs
    # to so titles are self-contained ("mcore 迭代31 …" instead of "迭代31 …").
    active_context = ""
    if project_name:
        from memorycore.subject_context import SUBJECT_PROMPT_INSTRUCTION, active_context_block
        active_context = active_context_block(project_name, project_path, scope)
        if active_context:
            system_prompt += SUBJECT_PROMPT_INSTRUCTION

    user_prompt = _build_user_prompt(
        messages,
        existing_memories or [],
        config.custom_instructions,
        active_context=active_context,
    )

    t0 = time.time()
    last_error = None
    for attempt in range(2):
        try:
            raw = _call_llm(system_prompt, user_prompt, config)
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                logger.warning("extraction: LLM call failed (attempt 1), retrying: %s", exc)
                time.sleep(1)

    elapsed = time.time() - t0

    if last_error is not None:
        logger.error("extraction: LLM call failed after 2 attempts: %s", last_error)
        try:
            from memorycore.storage.audit import log_audit_event
            log_audit_event(
                "extraction_failed",
                detail={"error": str(last_error), "elapsed_s": round(elapsed, 2), "model": config.model},
            )
        except Exception:
            pass
        return [], elapsed

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
    # Auto-add /v1 prefix ONLY when the base has no version segment yet.
    # OpenAI-compatible providers vary: /v1 (DeepSeek, CPA), /api/paas/v4 or
    # /api/coding/paas/v4 (Zhipu GLM). If the path already ends with /v<N>
    # or contains /v<N>/, append /chat/completions as-is.
    path = base.split("://", 1)[-1]
    if not re.search(r"/v\d+$|/v\d+/", path):
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
    if not re.search(r"/v\d+$|/v\d+/", base.split("://", 1)[-1]):
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
            text = str(item.get("content") or item.get("text") or "").strip()
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
                title=str(item.get("title") or "").strip(),
                linked_memory_ids=[str(x) for x in linked if x],
                raw_id=str(item.get("id", "")),
                importance=imp,
                memory_type=str(item.get("type", "")),
                subject=str(item.get("subject") or "").strip(),
                entities=[str(x) for x in item.get("entities", []) if str(x).strip()]
                if isinstance(item.get("entities"), list) else [],
            ))

    return facts
