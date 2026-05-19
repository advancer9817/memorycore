# Overmind-Inspired lmmcp Evolution Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 借鉴 Overmind 中真正有价值的产品机制，把 lmmcp 从“共享记忆存储 + context pack”推进到“可解释、可反馈、可预警、可协作的多 agent 记忆控制面”，同时保持本地优先、URL-based MCP 和多客户端中立。

**Architecture:** 不复制 Overmind 的 Claude Code 专用 hook/transcript 绑定；只吸收其认知层思路，并落到 lmmcp 的 MCP tools、SQLite schema、Qdrant index、curator、context pack 和 dashboard。所有新增能力遵守 hardening 文档中的前置约束：隐私过滤、candidate-first、memory is data not instruction、dry-run 默认、审计可追溯。

**Tech Stack:** Python 3.11+, FastMCP, SQLite + FTS5, memory_links graph, Qdrant, Ollama embeddings, OpenAI-compatible extraction LLM, pytest, dashboard.html.

---

## 1. Overmind 值得吸收的亮点

Overmind 不适合作为 lmmcp 的直接依赖或替代品，但它抓住了 Coding Agent 长期协作的真实痛点：会话断裂、经验无法复用、技能库过多导致上下文浪费、同类错误反复踩坑、Agent 缺少历史失败模式意识、长期记忆容易污染和陈旧。lmmcp 应吸收这些“产品判断”，但用更通用、更可审计的方式实现。

1. **设计方向正确：围绕 Coding Agent 失败模式设计记忆系统**
   - 记忆系统不应只是 RAG 搜索，而要服务“少重复踩坑、少浪费上下文、少丢失经验”。
   - 对 lmmcp 启发：所有新增能力都要围绕 coding-agent workflow 的实际收益评估，例如是否减少重复解释、是否减少错误修复轮次、是否帮助选择正确 skill。

2. **本地优先，但明确区分本地存储和外部推理**
   - Overmind 的 `memory.db`、`graph.db`、`memory/` 目录本地化是正确方向。
   - 但它仍可能把 transcript 片段发给 DeepSeek 做抽取、总结、选择，所以“全部本地”必须限定为“存储本地，推理可选外部”。
   - 对 lmmcp 启发：README/status/API response 要显式标注：SQLite/Qdrant 是本地事实源；DeepSeek/外部 LLM 只用于可选抽取；外部调用必须可关闭、可降级、可审计。

3. **轻量注入集成值得借鉴，但 lmmcp 应做 client-neutral 变体**
   - Overmind 的 Hook + include 模式很实用：SessionStart/UserPromptSubmit 生成 `injection.md`，再由 `CLAUDE.md` include，不改 Claude Code 本体。
   - 对 lmmcp 启发：核心仍保持 URL-based MCP；可额外提供“可选 client adapter 模板”，由适配器调用 `memory_context` 后生成本地 include 文件。
   - 边界：include 文件生成不属于核心事实源，不读取私有 transcript，不绕过 MCP，不默认启用；Claude/Codex/Gemini/OpenCode 都应可实现自己的薄 adapter。

4. **上下文注入不是简单搜索结果，而是任务相关的“认知包”**
   - 包含相关事实、最近经验、技能提示、风险警告、反馈摘要。
   - 对 lmmcp 启发：`memory_context` 应从 v1 的分组文本升级为 v2 的 structured context pack，保留 legacy markdown，同时返回 sections/warnings/recommendations/trace。

5. **知识图谱与关系扩展**
   - Overmind `graph.js` 的 10 类关系有启发：`depends_on`、`part_of`、`blocked_by`、`causes`、`solves`、`related_to`、`extends`、`conflicts_with`、`alternative_to`、`triggers`。
   - 对 lmmcp 启发：已有 `memory_links`，应扩展 relation type，并提供 graph traversal；无需新增独立 graph.db。
   - 映射建议：`blocked_by -> blocks/blocked_by`，`conflicts_with -> contradicts/conflicts_with`，`solves -> resolves`，`alternative_to -> alternative_to`，`triggers -> triggers`。

6. **危险预警 / search_warnings**
   - Overmind 基于 `blocked_by` / `conflicts_with` / `causes` 做 warning，比单纯 RAG 更进一步：不只是“找相关内容”，还判断“当前任务是否触发历史阻塞或冲突”。
   - 对 lmmcp 启发：新增 `memory_warnings`，从 links、feedback、stale/contradicted 状态、项目路径、任务文本中生成风险提示，并集成到 `memory_context` 的 warnings section。

7. **反馈闭环是长期记忆不变脏的关键**
   - Overmind 的反馈事件值得借鉴：`injected`、`referenced`、`helped`、`did_not_help`、`caused_confusion`。
   - 对 lmmcp 启发：现有 `memory_feedback` 应扩展为事件化反馈，区分“被注入”“被引用”“有帮助”“无帮助”“造成混淆”，并真正影响排序、curator、context pack 和 dashboard。

8. **技能推荐而不是全量加载**
   - Overmind README 提到把大量 Skill 从 Claude Code 原生扫描中移走，由任务选择 2-3 个，能减少 token 成本和上下文污染。
   - 对 lmmcp 启发：新增 skill recommendation，但只输出“建议加载哪些 skill + 为什么”，不自动写 skill，不自动修改 Hermes 配置，不强耦合 Claude Code。

9. **降级策略有意识，lmmcp 应把降级做成显式产品能力**
   - Overmind 的 fallback 包括：AI 选择失败后回退到关键词/短列表、`search_memory` 可关闭 `use_ai`、FTS 失败回退 LIKE、Hook 不可靠时 Worker idle consolidate、抽取前隐私过滤和噪音过滤。
   - 对 lmmcp 启发：每个智能能力都要有 deterministic fallback，并在 MCP response 中返回 `degraded`、`fallback_used`、`reason`。

10. **Episodic -> Semantic -> Procedural 演化**
    - 会话经验先作为 episodic candidate，稳定后晋升为 semantic/project memory，再沉淀为 procedural/skill candidate。
    - 对 lmmcp 启发：建立明确 lifecycle，而不是所有记忆长期同权重保留。

11. **Session summary / experience distillation**
    - 会话结束后压缩为可复用经验。
    - 对 lmmcp 启发：提供 `memory_session_digest` 工具，接受显式传入的会话消息，不读取客户端私有 transcript。

12. **低质量记忆 pruning**
    - 通过无效反馈和陈旧度降低记忆优先级。
    - 对 lmmcp 启发：curator 从 report-only/dry-run 进化到可审计的生命周期建议。

13. **认知状态可见性**
    - 让用户知道系统为什么注入某条记忆、为什么警告、为什么推荐 skill。
    - 对 lmmcp 启发：dashboard 增加 context trace、warning trace、skill recommendation trace、fallback/degraded trace。

---

## 2. 融入原则

### 2.1 吸收机制，不吸收绑定方式

只吸收 Overmind 的“认知层设计”：图谱、预警、反馈、技能偏好、记忆演化。

不吸收：

- Claude Code 私有 transcript 路径依赖；
- hook/injection 文件作为核心架构；
- 自动读取完整会话再上传外部 LLM；
- 自动创建 skill/写文件；
- README 先行的过度叙事。

### 2.2 SQLite 是事实源，Qdrant 是索引，MCP 是唯一正式接口

- 所有记忆和关系以 SQLite 为 source of truth。
- Qdrant 只做语义检索/去重索引，可重建。
- 所有 agent 通过 MCP URL 访问，不直接写 DB。

### 2.3 所有“智能”先输出建议，不直接执行破坏性动作

- warning 是提示，不是阻断。
- skill recommendation 是建议，不自动写 skill。
- lifecycle promotion 是 candidate，不自动替换真实事实。
- curator 默认 dry-run，apply 必须可审计。

### 2.4 可选适配器可以轻量，核心必须中立

- 可以提供 Claude Code `CLAUDE.md include`、Codex prompt include、Gemini/OpenCode 启动脚本等 adapter 模板。
- adapter 的唯一职责是调用 MCP `memory_context` / `memory_warnings` 并生成客户端可消费的本地上下文文件。
- adapter 不读取 transcript、不直接写 SQLite、不绕过隐私过滤、不成为 lmmcp 的必需路径。

### 2.5 每个 AI 能力必须有 deterministic fallback

- AI 选择失败时回退 FTS/关键词/最近高价值记录。
- FTS 失败时可回退 LIKE，但 response 必须标注 fallback。
- Qdrant/Ollama/DeepSeek 不可用时，核心 SQLite + MCP 工具仍可用。
- 所有 fallback/degraded 状态进入 response trace 和 dashboard。

---

## 3. 能力蓝图

| Overmind 亮点 | lmmcp 对应能力 | 新增/改造模块 | 优先级 |
|---|---|---|---|
| Coding Agent 痛点导向 | agent workflow effectiveness metrics | context trace, feedback stats, dashboard | P1 |
| 本地优先 + 外部推理限定 | local-first status + external-call policy | `models.py`, `extraction.py`, README/status | P0 |
| Hook + include 轻量集成 | optional include-file adapters | `docs/adapters/`, `scripts/adapters/` | P2 |
| 认知包注入 | Context Pack v2 | `build_context_pack`, `memory_context` | P0 |
| 风险预警 | `memory_warnings` MCP tool | `warnings.py`, `storage.py`, `server.py` | P0 |
| 图谱扩展 | Graph traversal over `memory_links` | `memory_graph_expand`, relation types | P1 |
| 技能偏好 | skill recommendation | `skill_recommender.py`, `skill_feedback` table | P1 |
| 反馈闭环 | feedback event taxonomy + weighted ranking | `memory_feedback`, `feedback_events`, curator, dashboard | P0 |
| 降级策略 | deterministic fallback + degraded trace | search/context/vector/extraction status | P0 |
| 记忆演化 | lifecycle candidates | `memory_lifecycle_report` | P1 |
| 会话蒸馏 | explicit session digest | `memory_session_digest` | P2 |
| 无效记忆修剪 | pruning suggestions | curator extension | P1 |
| 可解释性 | context/warning/skill/fallback trace | dashboard + MCP response metadata | P1 |

---

## 4. 实施阶段

## Phase 0: 先满足安全前置条件

本计划依赖以下 hardening 文档中的 P0 项：

- `docs/plans/2026-05-19-overmind-lessons-lmmcp-hardening.md`
- P0-1: 统一隐私过滤层。
- P0-2: Context Pack 注入防护。
- P0-4: 自动写入和状态变更审计日志。

如果这些未完成，可以先写接口和测试，但不要启用自动外部 LLM session digest 或自动 promotion。

---

## Phase 0.5: Local-first status and fallback contract

### Task 0.5.1: 明确本地存储与外部推理边界

**Objective:** 避免“全部本地”的模糊叙事，明确哪些能力本地完成，哪些能力可能调用外部 API。

**Files:**
- Modify: `README.md`
- Modify: `docs/status.md` or create it if missing
- Modify: `local_memory_mcp/models.py`
- Test: `tests/test_status_contract.py`

**Requirements:**

- README 增加能力状态表：SQLite/FTS5/local dashboard/local Qdrant/remote Qdrant/Ollama/DeepSeek。
- `memory_vector_status`、未来 `memory_extraction_status` 返回 local/remote/degraded/fallback 信息。
- 外部 LLM extraction 默认可通过 config/env 关闭。

### Task 0.5.2: 定义 fallback/degraded response contract

**Objective:** 把 Overmind 的 fallback 意识产品化，让每个 MCP response 可以解释是否降级。

**Files:**
- Modify: `local_memory_mcp/storage.py`
- Modify: `vector_store.py`
- Modify: `extraction.py`
- Test: `tests/test_degraded_contract.py`

**Response pattern:**

```python
{
  "data": ...,
  "trace": {
    "fallback_used": True,
    "degraded": True,
    "reason": "qdrant_unavailable_using_fts",
    "sources": ["sqlite_fts"]
  }
}
```

---

## Phase 1: Context Pack v2 + Warning Engine

### Task 1: 定义 Context Pack v2 返回结构

**Objective:** 把 `memory_context` 从“字符串 + records”升级为可解释结构，同时保持旧 `context` 字段兼容。

**Files:**
- Modify: `local_memory_mcp/storage.py`
- Modify: `local_memory_mcp/server.py`
- Test: `tests/test_context_pack_v2.py`

**Design:**

返回结构建议：

```python
{
  "context": "legacy markdown text",
  "sections": [
    {
      "name": "user_profile",
      "records": [
        {
          "id": "...",
          "title": "...",
          "snippet": "...",
          "type": "user_profile",
          "confidence": 0.9,
          "importance": 0.7,
          "feedback_score": 0.2,
          "updated_at": "...",
          "why_selected": ["fts_match", "high_importance", "positive_feedback"]
        }
      ]
    }
  ],
  "warnings": [],
  "recommendations": [],
  "quality": {...},
  "trace": {
    "query": "...",
    "sources": ["sqlite_fts"],
    "filtered_ids": [],
    "budget_chars": 8000
  }
}
```

**Verification:**

```bash
cd /home/advancer/project/local-memory-mcp
.venv/bin/python -m pytest tests/test_context_pack_v2.py -q
.venv/bin/python -m local_memory_mcp context "测试 context pack v2" --budget 1200
```

---

### Task 2: 在 context ranking 中加入 feedback 和 freshness

**Objective:** 让正反馈、高重要性、近期相关记忆更容易进入 context；负反馈、陈旧、低置信度记忆降权。

**Files:**
- Modify: `local_memory_mcp/storage.py`
- Test: `tests/test_context_ranking.py`

**Approach:**

新增内部排序函数：

```python
def memory_rank_score(row, *, query_match_score=1.0):
    return (
        query_match_score * 1.0
        + float(row["importance"] or 0) * 0.8
        + float(row["confidence"] or 0) * 0.5
        + max(min(float(row["feedback_score"] or 0), 5), -5) * 0.2
        + freshness_boost(row["updated_at"])
    )
```

注意：不要让 freshness 压过稳定高价值记忆；用户 profile、environment_fact 等可有较慢衰减。

**Verification:**

- 同等 FTS 命中时，正反馈记录排在负反馈记录前。
- `status != active` 默认不进入普通 context。

---

### Task 3: 新增 Warning Engine

**Objective:** 借鉴 Overmind `search_warnings`，在任务执行前基于历史记忆、链接关系和负反馈生成风险提示。

**Files:**
- Create: `local_memory_mcp/warnings.py`
- Modify: `local_memory_mcp/storage.py`
- Modify: `local_memory_mcp/server.py`
- Test: `tests/test_warnings.py`

**Warning sources:**

1. `memory_links.relation_type == "contradicts"`：存在冲突事实。
2. `memory_links.relation_type == "supersedes"`：有新事实替代旧事实。
3. `feedback_score < -0.5`：过去使用效果差。
4. `status in ('stale', 'contradicted')` 且 query 命中：提醒不要直接信任旧事实。
5. tags 包含 `risk:*`, `pitfall`, `warning`, `blocked`, `failed`。
6. metadata 中标注 `source="extraction"` 且 status=`candidate`：提醒未确认。

**MCP tool:**

```python
@mcp.tool()
def memory_warnings(task: str, project_path: str = "", scope: str = "global", limit: int = 10) -> list[dict[str, Any]]:
    """Return risk warnings relevant to a task from memory links, stale facts, contradictions, and negative feedback."""
```

**Verification:**

- 创建一条 active 事实和一条 contradicts link，查询相关 task，应返回 warning。
- 创建 low feedback 记忆，查询相关 task，应返回 warning。
- warning 返回 `severity`, `reason`, `memory_ids`, `suggested_action`。

---

### Task 4: 将 warnings 集成到 `memory_context`

**Objective:** Context pack 不只给“该记住什么”，还给“该小心什么”。

**Files:**
- Modify: `local_memory_mcp/storage.py`
- Test: `tests/test_context_warnings.py`

**Rules:**

- `memory_context` 调用 warning engine。
- markdown context 中增加 `## warnings` section。
- structured response 中增加 `warnings` 数组。
- warning 文本必须是建议，不是系统指令，避免被注入攻击滥用。

---

## Phase 2: Graph Expansion over existing memory_links

### Task 5: 扩展 relation types

**Objective:** 在不新增 graph.db 的情况下，让 `memory_links` 能表达 Overmind 类知识图谱。

**Files:**
- Modify: `local_memory_mcp/models.py`
- Modify: `local_memory_mcp/storage.py`
- Test: `tests/test_links.py`

**Current relation types:**

- `related_to`
- `supersedes`
- `contradicts`
- `supports`
- `part_of`

**Proposed additions inspired by Overmind graph.js:**

- `depends_on`
- `blocked_by` / `blocks`
- `causes`
- `solves` / `resolves`
- `extends`
- `conflicts_with`
- `alternative_to`
- `triggers`
- `uses`
- `belongs_to`
- `derived_from`
- `pitfall_for`

Keep existing lmmcp types: `related_to`, `supersedes`, `contradicts`, `supports`, `part_of`.

Warning-relevant relations: `blocked_by`, `blocks`, `conflicts_with`, `contradicts`, `causes`, `triggers`, `pitfall_for`.

**Verification:**

- `memory_link_add` accepts new relation types。
- invalid relation type 仍被拒绝。

---

### Task 6: 新增 `memory_graph_expand`

**Objective:** 根据起点 memory 或 task 查询扩展一跳/两跳相关记忆，给 agent 更完整的上下文图谱。

**Files:**
- Modify: `local_memory_mcp/storage.py`
- Modify: `local_memory_mcp/server.py`
- Test: `tests/test_graph_expand.py`

**MCP tool:**

```python
@mcp.tool()
def memory_graph_expand(
    query: str = "",
    memory_id: str = "",
    depth: int = 1,
    relation_types: list[str] | str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Expand related memories through memory_links from a query or memory id."""
```

**Return:**

```python
{
  "nodes": [{"id": "...", "title": "...", "type": "...", "status": "..."}],
  "edges": [{"source_id": "...", "target_id": "...", "relation_type": "...", "weight": 0.8}],
  "trace": {"start_ids": [...], "depth": 1}
}
```

**Verification:**

- depth=1 只返回直接边。
- depth=2 返回二跳但限制节点数。
- archived/stale 默认可返回但必须标注 status，不作为 active fact 注入。

---

## Phase 3: Skill Preference without auto-writing skills

### Task 7: 增加 skill feedback / recommendation 数据模型

**Objective:** 借鉴 Overmind 的 skill preference，但让 lmmcp 只负责推荐，不负责创建/修改 skill 文件。

**Files:**
- Modify: `local_memory_mcp/storage.py`
- Modify: `local_memory_mcp/server.py`
- Test: `tests/test_skill_recommendations.py`

**Schema idea:**

```sql
CREATE TABLE IF NOT EXISTS skill_feedback (
  id TEXT PRIMARY KEY,
  skill_name TEXT NOT NULL,
  task_pattern TEXT NOT NULL DEFAULT '',
  project_path TEXT NOT NULL DEFAULT '',
  score REAL NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  source_agent TEXT NOT NULL DEFAULT 'unknown',
  created_at TEXT NOT NULL
);
```

**Tools:**

```python
memory_skill_feedback(skill_name, task, score, note="", project_path="", source_agent="agent")
memory_skill_recommend(task, project_path="", limit=5)
```

**Recommendation factors:**

- exact/FTS match on task pattern；
- average score；
- recency；
- project_path match；
- linked `skill_candidate` records。

**Boundary:**

- 返回 skill 名称和理由。
- 不调用 Hermes `skill_manage`。
- 不写 `~/.hermes/skills`。

---

### Task 8: Context Pack 集成 skill recommendations

**Objective:** 让 agent 在开始任务时看到“可能应该加载哪些 skill”。

**Files:**
- Modify: `local_memory_mcp/storage.py`
- Test: `tests/test_context_skill_recommendations.py`

**Rules:**

- `memory_context` 增加 `recommendations.skills`。
- markdown context 增加 `## suggested_skills`。
- 每条推荐必须包含 reason 和 confidence。
- 不把推荐写成命令式系统指令，只说“Consider loading”。

---

## Phase 3.5: Feedback event taxonomy

### Task 8.5: 扩展 feedback_events 为事件化反馈

**Objective:** 借鉴 Overmind 的 `injected/referenced/helped/did_not_help/caused_confusion`，让反馈不仅是分数，而是可用于排序和淘汰的事件流。

**Files:**
- Modify: `local_memory_mcp/storage.py`
- Modify: `local_memory_mcp/server.py`
- Modify: `dashboard.html`
- Test: `tests/test_feedback_events.py`

**Event types:**

- `injected`: 记忆进入 context pack。
- `referenced`: agent/user 明确引用该记忆。
- `helped`: 该记忆帮助完成任务。
- `did_not_help`: 该记忆无帮助。
- `caused_confusion`: 该记忆误导或造成混淆。

**Ranking effect:**

- `helped` 提升 ranking。
- `did_not_help` 降低 ranking。
- `caused_confusion` 强降权，并进入 warning/curator。
- `injected` 只计曝光，不等同正反馈。

---

## Phase 4: Lifecycle Evolution

### Task 9: 新增 lifecycle report

**Objective:** 将 Overmind 的 episodic -> semantic -> procedural 演化做成可审计建议，而非自动黑箱。

**Files:**
- Modify: `local_memory_mcp/storage.py`
- Modify: `local_memory_mcp/server.py`
- Test: `tests/test_lifecycle_report.py`

**MCP tool:**

```python
@mcp.tool()
def memory_lifecycle_report(dry_run: bool = True, limit: int = 200) -> dict[str, Any]:
    """Suggest memory promotions/demotions: episodic->project/user memory, skill_candidate promotion, stale/archive candidates."""
```

**Promotion examples:**

- `episodic_memory` with repeated positive feedback + similar title across projects -> `project_memory` candidate。
- `skill_candidate` with high importance + positive feedback -> recommend Hermes skill creation。
- `raw_event` older than N days with no access -> archive candidate。
- contradicted fact with superseding active fact -> mark stale candidate。

**Verification:**

- dry_run 不改变 DB。
- apply 模式只改变 status 或创建 candidate，不删除。
- 所有 apply 需要 audit event。

---

### Task 10: Curator dashboard 增强

**Objective:** 让用户看见“为什么推荐晋升/降级/技能化”。

**Files:**
- Modify: `dashboard.html`
- Modify: `local_memory_mcp/storage.py` (`export_html`)
- Test: `tests/test_html.py`

**Dashboard additions:**

- Warning candidates panel。
- Skill recommendations panel。
- Lifecycle suggestions panel。
- Context trace panel：��近一次 context pack 使用了哪些 records、为什么选中。

---

## Phase 5: Explicit Session Digest

### Task 11: 新增 `memory_session_digest`

**Objective:** 借鉴 Overmind 会话总结，但不读取任何客户端私有 transcript；只处理调用方显式传入的消息。

**Files:**
- Modify/Create: `local_memory_mcp/session_digest.py`
- Modify: `local_memory_mcp/server.py`
- Test: `tests/test_session_digest.py`

**MCP tool:**

```python
@mcp.tool()
def memory_session_digest(
    messages: list[dict[str, str]],
    project_path: str = "",
    agent_id: str = "agent",
    dry_run: bool = True,
) -> dict[str, Any]:
    """Summarize an explicit session into candidate memories, decisions, pitfalls, and skill candidates."""
```

**Output categories:**

- durable facts；
- decisions；
- pitfalls/warnings；
- unresolved blockers；
- skill candidates；
- no-save items。

**Important boundary:**

- 必须经过 privacy sanitizer。
- 默认 dry_run。
- 只写 candidate。
- 不读取 `~/.claude`、`~/.codex`、Hermes session DB。

---

## Phase 5.5: Optional include-file adapters

### Task 11.5: 提供 Hook/include 思路的 client-neutral adapter 模板

**Objective:** 借鉴 Overmind Hook + include 的轻量集成方式，但不让它成为 lmmcp 核心依赖。

**Files:**
- Create: `docs/adapters/include-file-adapters.md`
- Create: `scripts/adapters/render_context_include.py`
- Test: `tests/test_include_adapter.py`

**Behavior:**

- adapter 调用 HTTP MCP `memory_context`。
- 输出一个本地 markdown include 文件，例如 `.lmmcp/context.md`。
- 不读取 transcript。
- 不直接写 SQLite。
- 可被 Claude Code 的 `CLAUDE.md` include、Codex 启动 prompt、Gemini/OpenCode wrapper 使用。

**Verification:**

- 在临时目录运行 adapter，输入 task，生成 include markdown。
- MCP 不可用时生成明确 degraded 文件，而不是静默失败。

---

## 5. 推荐优先级

### P0: 立即做

1. 明确 local-first/external-reasoning 状态和 degraded response contract。
2. Context Pack v2 structure。
3. Feedback/freshness ranking。
4. Feedback event taxonomy: `injected/referenced/helped/did_not_help/caused_confusion`。
5. Warning Engine + `memory_warnings`。
6. Warnings integrated into `memory_context`。

理由：这些最能体现 Overmind 的价值，又能建立在 lmmcp 现有 SQLite/links/feedback 上，风险可控。

### P1: 第二阶段

1. 扩展 relation types。
2. `memory_graph_expand`。
3. skill feedback / recommendation。
4. lifecycle report。
5. dashboard trace。

理由：这些增强“认知层”和可解释性，但需要更多 schema 和 UI 工作。

### P2: 第三阶段

1. `memory_session_digest`。
2. 更复杂的自动 promotion。
3. connector adapters。

理由：涉及 LLM 总结和更多隐私风险，必须等 hardening P0 完成后再启用。

---

## 6. 与现有 hardening 计划的关系

本计划是“吸收亮点”。

已有文档是“避免踩坑”：

`docs/plans/2026-05-19-overmind-lessons-lmmcp-hardening.md`

建议执行顺序：

1. hardening P0-1 privacy redaction。
2. hardening P0-2 context injection guard。
3. 本计划 Phase 1 Context Pack v2 + Warning Engine。
4. hardening P0-4 audit。
5. 本计划 Phase 2/3 graph + skill recommendation。
6. 本计划 Phase 4 lifecycle。
7. 本计划 Phase 5 session digest。

---

## 7. Non-goals

本计划明确不做：

1. 不把 lmmcp 改造成 Claude Code 插件。
2. 不实现 hook-based injection 文件。
3. 不自动扫描客户端私有 transcript。
4. 不自动写 Hermes skill 文件。
5. 不把 LLM 生成内容直接提升为 active 高可信事实。
6. 不把 Qdrant 当事实源。
7. 不绕过 MCP server 直接让 agent 写 SQLite。

---

## 8. 验证总清单

每个阶段完成后运行：

```bash
cd /home/advancer/project/local-memory-mcp
.venv/bin/python -m pytest -q
.venv/bin/python -m local_memory_mcp context "实现一个需要历史经验和风险预警的任务" --budget 1600
.venv/bin/python -m local_memory_mcp curator --summary-only
```

新增测试文件建议：

```text
tests/test_context_pack_v2.py
tests/test_context_ranking.py
tests/test_warnings.py
tests/test_context_warnings.py
tests/test_graph_expand.py
tests/test_skill_recommendations.py
tests/test_context_skill_recommendations.py
tests/test_lifecycle_report.py
tests/test_session_digest.py
```

---

## 9. 最终产品形态

完成后，lmmcp 的定位可以从：

> 多 agent 共享长期记忆总线

升级为：

> 多 agent 共享的本地认知控制面：能检索事实、解释上下文选择、提示历史风险、推荐可用技能、管理记忆生命周期，并通过 URL-based MCP 服务所有客户端。

这比 Overmind 更通用：

- 不绑定 Claude Code；
- 不依赖私有 transcript；
- 不需要 hook injection；
- 所有能力都可被 Hermes、Codex、Claude Code、Gemini、OpenCode 等 MCP client 复用；
- 关键自动化都可审计、可 dry-run、可降级。
