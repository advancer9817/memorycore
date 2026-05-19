# Agent Memory Hook Contract for lmmcp

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 为 lmmcp 设计一套跨 Agent 的 Hook / Wrapper / MCP 记忆接入协议，使 Hermes、Claude Code、Codex、Kiro、OpenCode、Gemini CLI 等 Agent 能在对话前主动获取前置背景、对话中主动读写 MCP、对话后自动沉淀长期记忆。

**Architecture:** lmmcp 保持为 client-neutral 的记忆服务与 URL-based MCP/HTTP API；Hook、include 文件、CLI wrapper 都作为可选 adapter。核心不绑定 Claude Code transcript、不读取私有客户端状态、不把记忆当作不可审计指令注入，而是通过 context pack、session ingest、feedback events、warnings、trace 字段形成可解释闭环。

**Tech Stack:** Python 3.11+, FastMCP, SQLite + FTS5, Qdrant/Ollama embeddings, optional OpenAI-compatible extraction LLM, shell wrapper scripts, pytest, dashboard trace.

---

## 1. 背景与结论

用户真正需要的是：

1. 其他 Agent 能主动读取 lmmcp 中的历史背景。
2. 其他 Agent 能主动向 MCP 写入事实、决策、项目知识、偏好与反馈。
3. 每次新对话开始前，Agent 自动调用 lmmcp 获取前置上下文。
4. 多个 Agent 跨会话、跨工具共享一套长期记忆。

这完全可行，但不应该复制 Overmind 的 Claude Code 单客户端绑定。更适合 lmmcp 的形态是：

```text
Agent Lifecycle Hook / Wrapper
        ↓
Context Pack API / MCP Tool
        ↓
lmmcp: memory + vector + graph + feedback + lifecycle
        ↑
Session Ingest / Feedback Events
        ↑
Hermes / Claude Code / Codex / Kiro / OpenCode / Gemini CLI / other agents
```

核心判断：

- lmmcp 应成为跨 Agent 的 memory substrate。
- Hook 只负责 Agent 生命周期接入，不负责存储真相。
- MCP/HTTP API 是核心边界，include 文件和 shell wrapper 是薄适配层。
- 写入必须经过抽取、去重、隐私过滤、candidate-first 和反馈闭环。

---

## 2. 设计原则

### 2.1 client-neutral 优先

核心服务不能依赖某一个 Agent 的私有 transcript 路径、hook 格式或插件系统。

允许：

- Hermes profile 前置读取。
- Claude Code include adapter。
- Codex / OpenCode / Gemini CLI wrapper。
- Kiro adapter。

不允许：

- lmmcp 核心硬编码 `~/.claude/projects/*.jsonl`。
- 核心 schema 依赖 Claude Code event 名称。
- 把 include 文件作为事实源。

### 2.2 memory is data, not instruction

注入给 Agent 的内容必须明确标记为背景、事实候选、偏好、历史决策或风险提示，而不是不可质疑的系统指令。

Context pack 应包含：

- source id
- score
- confidence
- status
- project_path / scope
- created_at / updated_at
- trace reason

### 2.3 before-agent 获取背景，after-agent 沉淀记忆

生命周期分为三类动作：

1. before-agent / before-turn：获取 context pack。
2. during-agent：Agent 主动调用 MCP search/get/add/feedback。
3. after-agent / session-end：提交 session digest 或 messages，进入 ingest/extract/dedup 流程。

### 2.4 fallback 是产品能力

任意 Hook 或智能能力失败时，Agent 仍应继续执行。

要求：

- 默认超时 1-2 秒。
- lmmcp 不可用时返回 degraded context。
- 外部 LLM 抽取不可用时使用 deterministic fallback 或跳过抽取。
- 所有响应包含 `degraded`、`fallback_used`、`reason`、`sources`。

### 2.5 写入默认 candidate-first

除用户明确要求“记住这个”或工具调用明确标记高可信，自动抽取结果默认进入 candidate/staged 状态，不直接成为高优先级 active memory。

---

## 3. 最小协议

### 3.1 `context_pack`

用途：对话前获取前置背景。

建议作为 MCP tool 与 HTTP endpoint 同时暴露。

输入：

```json
{
  "agent": "claude-code",
  "project_path": "/home/advancer/project/local-memory-mcp",
  "task": "修复 Qdrant dedup bug",
  "session_id": "optional-session-id",
  "token_budget": 2000,
  "include": {
    "user_profile": true,
    "project_memory": true,
    "skills": true,
    "warnings": true,
    "recent_decisions": true
  }
}
```

输出：

```json
{
  "context": "可直接注入 prompt/include 的压缩背景",
  "sections": {
    "user_preferences": [],
    "project_conventions": [],
    "relevant_memories": [],
    "warnings": [],
    "suggested_skills": []
  },
  "sources": [
    {
      "id": "memory-id",
      "score": 0.83,
      "type": "decision",
      "reason": "matched task and project_path"
    }
  ],
  "degraded": false,
  "fallback_used": false,
  "reason": ""
}
```

### 3.2 `ingest_session`

用途：对话后写回长期记忆候选。

输入：

```json
{
  "agent": "codex",
  "project_path": "/home/advancer/project/foo",
  "messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "artifacts": [
    {"path": "docs/plan.md", "kind": "plan"}
  ],
  "metadata": {
    "session_id": "optional-session-id",
    "started_at": "2026-05-19T10:00:00+08:00",
    "ended_at": "2026-05-19T10:20:00+08:00"
  }
}
```

输出：

```json
{
  "added": 2,
  "updated": 1,
  "skipped": 5,
  "candidates": [],
  "warnings": [],
  "degraded": false
}
```

### 3.3 `memory_feedback_event`

用途：让 Agent 或 Hook 标记某条记忆在本轮是否有用。

建议事件：

```text
injected
referenced
helped
did_not_help
caused_confusion
stale
contradicted
```

输入：

```json
{
  "memory_id": "memory-id",
  "event": "helped",
  "agent": "hermes/default",
  "project_path": "/home/advancer/project/local-memory-mcp",
  "session_id": "optional-session-id",
  "note": "帮助选择了正确的 MCP server URL 模式"
}
```

输出：

```json
{
  "ok": true,
  "memory_id": "memory-id",
  "event": "helped",
  "updated_feedback_score": 0.72
}
```

---

## 4. Adapter 设计

### 4.1 Hermes adapter

Hermes 是最适合优先集成的入口，因为它已经具备：

- MCP tools
- profiles
- skills
- session_search
- memory tool
- prompt builder / SOUL
- multi-agent router

短期实现：

- 在 default/coord/impl/qa/review 等 profile 的 SOUL 或 router prompt 中写入：任务开始时调用 lmmcp `memory_context/context_pack`，复杂任务结束后调用 `memory_ingest/ingest_session`。
- 保持人工可见：在最终总结中说明是否使用了 memory context。

中期实现：

- 在 Hermes prompt builder 或 conversation loop 中增加可配置 preflight context provider。
- 配置项示例：

```yaml
memory_hooks:
  enabled: true
  provider: lmmcp
  before_turn: true
  after_session: true
  timeout_ms: 1500
  token_budget: 2000
```

### 4.2 Generic CLI wrapper

用于无稳定 Hook 的 Agent，例如 Codex、OpenCode、Gemini CLI。

命令形态：

```bash
lmmcp-agent-wrapper \
  --agent codex \
  --project /home/advancer/project/foo \
  --task "实现登录模块" \
  -- codex
```

执行流程：

```text
1. 读取当前目录、agent 名称、task。
2. 调用 lmmcp context_pack。
3. 把 context pack 拼接到 prompt 前置区或写入临时 include 文件。
4. 启动目标 Agent。
5. 捕获输出或 transcript。
6. 调用 ingest_session。
7. 根据引用情况发送 feedback events。
```

### 4.3 Claude Code include adapter

可借鉴 Overmind 的 Hook + include 模式，但只作为薄 adapter。

允许：

- before hook 调用 lmmcp context_pack。
- 生成 `.agent/context/claude-code-memory.md`。
- 由 `CLAUDE.md` include。
- session end hook 调用 ingest_session。

不允许：

- 核心读取 Claude Code 私有 transcript。
- 核心依赖 Claude Code event 格式。
- include 文件绕过 MCP 成为事实源。

### 4.4 Kiro / 其他 IDE Agent adapter

原则同 generic wrapper：

- 优先使用可配置前置 prompt 或 workspace context 文件。
- 不能修改 Agent 内核时，用 wrapper 或 IDE 启动脚本。
- 所有写入都归一化为 ingest_session schema。

---

## 5. 建议目录结构

```text
local-memory-mcp/
  docs/
    hook-contract.md
    adapters.md
  src/local_memory_mcp/
    hook_contract.py
    context_pack.py
    ingestion.py
    feedback.py
    adapters/
      __init__.py
      hermes.py
      claude_code.py
      codex.py
      generic_cli.py
  scripts/
    lmmcp-before-agent
    lmmcp-after-agent
    lmmcp-agent-wrapper
  tests/
    test_context_pack_contract.py
    test_ingest_session_contract.py
    test_feedback_events.py
    test_agent_wrapper.py
```

---

## 6. 分阶段实施计划

### Phase 0: 文档与协议冻结

**目标:** 先冻结 Hook Contract，避免先写 adapter 后协议漂移。

**文件:**

- Create: `docs/hook-contract.md`
- Create: `docs/adapters.md`

**验收:**

- 明确 before-agent、during-agent、after-agent 三类动作。
- 明确 context_pack、ingest_session、feedback_event schema。
- 明确 fallback/degraded 字段。
- 明确哪些属于核心，哪些属于 adapter。

### Phase 1: context_pack v2

**目标:** 将现有 `memory_context` 演进为结构化 context pack。

**文件:**

- Modify: `local_memory_mcp/storage.py`
- Modify: `local_memory_mcp/server.py`
- Test: `tests/test_context_pack.py`

**能力:**

- 返回 legacy markdown context。
- 返回 structured sections。
- 返回 sources/trace。
- 返回 warnings/suggested_skills 占位。
- 返回 degraded/fallback_used/reason。

### Phase 2: ingest_session

**目标:** 增加显式 session ingest API，不读取客户端私有 transcript。

**文件:**

- Modify: `local_memory_mcp/server.py`
- Modify: `extraction.py`
- Modify: `dedup.py`
- Test: `tests/test_session_ingest.py`

**能力:**

- 接受统一 messages schema。
- 调用隐私过滤。
- 调用抽取与去重。
- 默认写入 candidate 或低置信 active。
- 返回 added/updated/skipped/candidates。

### Phase 3: feedback events

**目标:** 把现有 `memory_feedback` 从简单分数扩展为事件化反馈。

**文件:**

- Modify: `local_memory_mcp/models.py`
- Modify: `local_memory_mcp/storage.py`
- Modify: `local_memory_mcp/server.py`
- Test: `tests/test_feedback_events.py`

**事件:**

- injected
- referenced
- helped
- did_not_help
- caused_confusion
- stale
- contradicted

**验收:**

- event append-only。
- feedback score 可从事件聚合。
- curator 能识别低质量或混淆记忆。

### Phase 4: generic CLI wrapper

**目标:** 让无原生 Hook 的 CLI Agent 也能使用 lmmcp。

**文件:**

- Create: `scripts/lmmcp-agent-wrapper`
- Create: `scripts/lmmcp-before-agent`
- Create: `scripts/lmmcp-after-agent`
- Test: `tests/test_agent_wrapper.py`

**验收:**

- wrapper 能在 lmmcp 不可用时降级继续运行。
- wrapper 不记录 secret。
- wrapper 支持 `--agent`、`--project`、`--task`、`--token-budget`。
- wrapper 可把 context 输出为 markdown 或 JSON。

### Phase 5: Hermes adapter

**目标:** 让 Hermes profiles 稳定使用 lmmcp 前置背景和结束沉淀。

**方式:**

- 短期：profile SOUL / router prompt 约定。
- 中期：Hermes config + prompt builder preflight provider。

**验收:**

- default/coord/impl/qa/review 可读取 context_pack。
- 复杂任务结束后可调用 ingest_session。
- 不破坏 Hermes prompt caching 与 toolset 规则。

### Phase 6: Claude Code include adapter

**目标:** 提供可选 Claude Code 集成模板。

**文件:**

- Create: `adapters/claude-code/README.md`
- Create: `adapters/claude-code/hooks/before-agent.sh`
- Create: `adapters/claude-code/hooks/after-agent.sh`
- Create: `adapters/claude-code/CLAUDE.include.example.md`

**验收:**

- include 文件由 adapter 生成。
- lmmcp 核心不依赖 Claude Code 路径。
- Hook 失败不影响 Claude Code 正常运行。

---

## 7. 风险与防线

| 风险 | 表现 | 防线 |
|---|---|---|
| 上下文污染 | 注入过多旧记忆误导 Agent | token budget、relevance score、trace、stale 降权 |
| 错误记忆固化 | Agent 总结错了并长期复用 | candidate-first、confidence、feedback、contradiction detection |
| 隐私泄露 | transcript 中包含 token/连接串 | secret redaction、PII filter、ignore patterns、默认本地优先 |
| Hook 失败阻断 Agent | lmmcp 挂了导致 Agent 不能用 | timeout、degraded、fallback、继续执行 |
| 多 Agent 并发写入 | 重复、覆盖、脏数据 | SQLite WAL、dedup、source_agent、session_id、append-only feedback |
| Agent 格式差异 | transcript 不统一 | adapter 层解析，核心只接收统一 schema |
| 记忆变成指令 | Agent 把历史偏好当最高优先级 | memory is data not instruction、来源标注、置信度 |

---

## 8. 非目标

本计划不做：

- 不直接复制 Overmind。
- 不把 Claude Code 作为唯一或主架构。
- 不读取任意 Agent 私有 transcript 作为核心逻辑。
- 不默认把所有会话全文写入长期记忆。
- 不默认自动加载所有 skill。
- 不让 Hook 写入未过滤 secret。
- 不要求所有 Agent 都支持原生 Hook；wrapper 是一等适配方式。

---

## 9. 成功标准

实现完成后，应满足：

1. 任意 Agent 能通过 MCP/HTTP 获取任务相关 context pack。
2. 任意 Agent 能通过统一 schema 写回 session digest。
3. context pack 能解释为什么注入某条记忆。
4. feedback events 能影响后续排序和 curator。
5. lmmcp 不可用时 Agent 仍能正常运行。
6. Hermes profiles 可稳定进行对话前记忆读取。
7. Claude Code/Codex/Kiro 等通过 adapter 接入，而不是污染核心。
8. 用户能在 dashboard 或 trace 中看到注入、引用、反馈、降级记录。

---

## 10. 最终建议

优先级建议：

1. P0：冻结 hook contract 文档。
2. P0：将 `memory_context` 演进为 `context_pack` v2。
3. P1：增加 `ingest_session`。
4. P1：增加 feedback event taxonomy。
5. P1：做 Hermes profile 前置读取。
6. P2：做 generic CLI wrapper。
7. P2：做 Claude Code include adapter。
8. P3：接入 warning engine、skill recommendation 和 dashboard trace。

最关键的产品判断：

```text
lmmcp 不应该成为某个 Agent 的插件；
lmmcp 应该成为所有 Agent 的共享记忆控制面。
```
