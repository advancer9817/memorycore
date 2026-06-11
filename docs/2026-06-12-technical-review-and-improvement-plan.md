# MemoryCore 技术框架审查报告

> 审查日期：2026-06-12
> 审查范围：后端架构、LLM 治理管线、前端管理界面
> 审查目标：识别记忆质量、连续性、自动治理、前端配套的改进空间

---

## 一、当前技术框架概览

### 1.1 系统架构

```
┌─────────────────────────────────────────────────────┐
│  Claude Code / MCP Clients                          │
│  ↕ MCP Protocol (45 tools)                          │
├─────────────────────────────────────────────────────┤
│  FastMCP Server (server.py, port 8318)              │
│  ├── MCP Tool Layer (45 tools)                      │
│  ├── REST API Layer (frontend.py, /api/*)            │
│  └── Auto-Curator Daemon Thread (6h interval)       │
├─────────────────────────────────────────────────────┤
│  Core Logic                                         │
│  ├── extraction.py   — LLM fact extraction          │
│  ├── dedup.py        — vector dedup at write time   │
│  ├── storage/crud.py — CRUD operations              │
│  ├── storage/search.py — FTS + vector search        │
│  ├── storage/curator.py      — rule-based curation  │
│  ├── storage/curator_llm.py  — LLM-enhanced curation│
│  ├── storage/governance.py   — policy gate + apply   │
│  ├── storage/mutation_executor.py — batch mutations  │
│  ├── storage/rollup.py       — episodic → durable   │
│  ├── storage/atomization.py  — compound → atomic     │
│  └── storage/temporal_governance.py — auto-supersede │
├─────────────────────────────────────────────────────┤
│  Storage                                            │
│  ├── SQLite (WAL) + FTS5 full-text search           │
│  └── Qdrant (nomic-embed-text, 768d vectors)        │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  Frontend (Next.js 15 + React 19, port 18318)       │
│  ├── Dashboard (/)       — stats + intelligence     │
│  ├── Memories (/memories) — list + filters          │
│  ├── Memory Detail (/memory/[id])                   │
│  ├── Governance (/governance) — decisions + actions │
│  ├── Graph (/graph)      — 3D force-directed graph  │
│  ├── Apps (/apps)        — connected apps           │
│  └── Settings (/settings) — config                  │
└─────────────────────────────────────────────────────┘
```

### 1.2 数据模型

**memories 表**（核心）：

| 字段 | 类型 | 用途 |
|------|------|------|
| id | TEXT PK | UUID |
| type | TEXT | 10 种类型（user_profile, environment_fact, agent_architecture, project_memory, episodic_memory, timeline_event, decision, feedback, skill_candidate, raw_event） |
| status | TEXT | 6 种状态（active, stale, archived, contradicted, candidate, superseded） |
| scope | TEXT | 作用域，默认 global |
| title, content | TEXT | 记忆标题和内容 |
| importance | REAL | 0.0-1.0 长期价值评分 |
| confidence | REAL | 0.0-1.0 置信度，可衰减 |
| feedback_score | REAL | 用户反馈累积分 |
| effectiveness_score | REAL | 注入有效性评分 |
| injected_count | INT | 被注入到上下文的次数 |
| decay_policy | TEXT | 衰减策略（review） |
| superseded_by | TEXT | 被替代的记忆 ID |
| fact_lineage_root | TEXT | 事实谱系根节点 |
| valid_from, valid_until | TEXT | 时间有效范围 |

**关联表**：
- `memory_links`（关系链接，8 种关系类型）
- `memory_entities`（实体提取，含 aliases）
- `feedback_events`（反馈事件日志）
- `audit_events`（审计事件日志）
- `governance_decisions`（治理决策，含 LLM trace）
- `governance_runs`（治理运行记录）
- `governance_executions`（执行记录）
- `governance_mutation_log`（变更日志，含 before/after/inverse）
- `agent_messages`（智能体间消息）
- `agent_presence`（智能体在线状态）
- `context_quality_events`（上下文质量事件）
- `agent_capabilities`（智能体能力注册）

### 1.3 记忆生命周期

```
Text Input
  → extraction.py (LLM fact extraction, importance 0-1)
  → dedup.py (vector similarity: SKIP≥0.92, UPDATE≥0.78, LINK≥0.55)
  → crud.py (SQLite write + Qdrant vector sync)
  → temporal_governance.py (auto-supersession check)
  → status: candidate → active (via curator promotion)

Ongoing:
  → rollup.py: episodic_memory → durable memory (≥30 records or ≥5 after 24h)
  → atomization.py: compound → atomic (≥600 chars rule-based)
  → curator.py: promotion, staleness, decay, archiving, revival (every 6h)
  → curator_llm.py: semantic dedup, contradiction, importance re-eval, split (cron only)
  → governance.py: policy gate → needs_review / auto_approved / rejected
  → mutation_executor.py: batch apply with before/after snapshots + rollback
```

### 1.4 设计理念

MemoryCore 的核心设计理念是：

1. **分层治理**：所有变更必须经过 governance pipeline（policy gate → approval → execution → audit），确保可追溯、可回滚
2. **规则 + LLM 双引擎**：rule-based curator 处理确定性规则（TTL、衰减、阈值），LLM curator 处理语义判断（去重、矛盾、重评）
3. **宽进严出**：记忆以 `candidate` 状态进入，通过 curator 评估后提升为 `active`
4. **向量 + 全文混合搜索**：Qdrant 语义搜索 + FTS5 关键词搜索
5. **Auto-Governance Cockpit**：UI 的职责是证明系统在正常工作，而非要求用户做系统的工作

---

## 二、发现的问题与改进空间

### 2.1 Critical — 数据完整性问题

#### 问题 C1：LLM Curator 冷却注册表为内存变量，跨进程丢失

**文件**：`memorycore/storage/curator_llm.py:39-49`

```python
_reviewed_memory_ids: dict[str, float] = {}  # 内存 dict，进程重启即丢失
_REVIEW_COOLDOWN_SECONDS = 7200   # 2 hours
```

**影响**：`run_curator.sh` cron 每次以新 Python 进程运行，冷却状态全部丢失。每次运行都重新分析全部记忆，导致：
- 浪费 LLM 调用（每小时重复分析 1000+ 条记忆）
- 可能产生重复 governance decisions（虽有 candidate_hash 去重，但不同时间产生的 hash 不同）

**修复方案**：新增 `curator_review_log` 表持久化冷却状态。

---

#### 问题 C2：Daemon 线程不运行 LLM Curator

**文件**：`memorycore/server.py:846-876`

```python
def _start_auto_curator(interval_hours: float = 6.0):
    def _loop():
        while True:
            rollup = rollup_report(dry_run=False)        # ✅ 运行
            result = curator_report(dry_run=False)         # ✅ 运行
            # ❌ 缺少: run_llm_curator()
            time.sleep(interval_hours * 3600)
```

**影响**：没有配置 systemd cron 的环境（Docker、开发环境、非 Linux 部署）永远不会执行语义去重、矛盾检测、重要性重评和拆分检测。

**修复方案**：在 daemon `_loop()` 中添加 LLM curator 调用，可配置独立间隔。

---

#### 问题 C3：向量同步 fire-and-forget，失败静默丢失

**文件**：`memorycore/storage/crud.py` 的 `_sync_to_vector()`

**影响**：Qdrant 故障（网络超时、进程退出、磁盘满）时，SQLite 记录正常写入但向量索引缺失该条记忆。语义搜索和去重将永久遗漏此记忆。仅有 `memory_rebuild_vectors` 手动全量重建可修复，且用户通常不会意识到不一致。

**修复方案**：新增 `vector_sync_queue` 表，失败时入队，后台线程定期重试。

---

### 2.2 High — 功能缺陷

#### 问题 H1：LLM Curator 有时返回 0 变更

**表现**：有大量记忆（100+）但 LLM curator 报告显示 0 条 semantic_duplicates、0 条 contradictions、0 条 importance_reassessments。

**根因分析**：

1. **冷却过滤清空候选**（与 C1 相关）：如果在 2h 内运行过，内存 dict 中的冷却记录会过滤掉所有记忆
2. **Importance 重评的 "keep" 过滤**：`curator_llm.py:421` — 如果 LLM 返回 `action == "keep"` 且分数变化 < 0.05，结果被跳过。保守的 LLM 可能大部分返回 "keep"
3. **Candidate hash 去重**：`governance.py:240-251` — 已有相同 hash 的 decision 时不创建新的
4. **缺少诊断日志**：report summary 不包含中间步骤计数（过滤前后候选数、LLM 调用次数、跳过的 "keep" 数量），用户无法定位问题

**修复方案**：在 report summary 中添加诊断字段，并修复 C1。

---

#### 问题 H2：自动替换仅使用词法相似度

**文件**：`memorycore/storage/temporal_governance.py:36-45`

```python
def _similarity(left, right):
    sequence_score = SequenceMatcher(None, left_text, right_text).ratio()
    lexical_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    return round((sequence_score * 0.65) + (lexical_score * 0.35), 4)
```

**影响**：语义相同但措辞不同的记忆（如 "用户偏好暗色主题" vs "dark mode is the user's preferred setting"）无法被检测为候选替换。

**修复方案**：加入向量余弦相似度作为第三信号。

---

#### 问题 H3：Dashboard 未按已决策方案重设计

**现状**：Dashboard 由两个巨型组件（Install.tsx 785行 + MemoryIntelligenceCenter.tsx 972行）构成，包含已决定移除的元素：
- "Run Curator" 和 "Run LLM" 按钮（应移至 Governance 页面）
- "Open Queue" 和 "Open Ops" 两个按钮（应合并为 "前往治理"）
- 底部无关内容（应为治理/运营区域）

**修复方案**：按照 DESIGN.md 中已确定的 Auto-Governance Cockpit 方向拆分重构。

---

### 2.3 Medium — 优化空间

#### 问题 M1：LLM Prompt 缺少时间上下文

**文件**：`memorycore/storage/curator_llm.py`

当前 importance 重评 prompt 仅包含 `injected_count` 和 `feedback_score`，缺少 `last_accessed_at`、`last_injected_at`、创建距今时间等时间维度信息。LLM 无法判断一条记忆是否因为长期未被使用而过时。

#### 问题 M2：LLM Curator 无进度追踪

**文件**：`memorycore/frontend.py:86-104`

当前 `_run_llm_curator_job()` 只在完成/失败时更新 job 状态，运行期间无进度信息。1000 条记忆 × 10/batch = 100 次 LLM 调用可能需要 10+ 分钟，用户无法知道当前进度。

#### 问题 M3：Governance 页面缺少运行分组

同一次 LLM curator 运行产生的多个 decisions 在治理表中散落显示，用户无法看到"这一批 decisions 来自同一次分析运行"。

---

## 三、已有优势（保持并强化）

### 3.1 治理管线设计优秀
所有 LLM 建议都必须经过 `create_governance_decision()` → `policy_gate()` → manual/auto approval → `execute_batch()` 的管线，不会直接修改数据。这是生产级别的设计。

### 3.2 Mutation Executor 具备完整回滚能力
`governance_mutation_log` 记录 `before_json`、`after_json`、`inverse_json`，支持精确回滚。

### 3.3 多层去重机制
- 写入时向量去重（dedup.py，SKIP/UPDATE/LINK 三级阈值）
- 运行时 LLM 语义去重（curator_llm.py）
- Atomic fact hash 去重（防止拆分产生重复子记忆）

### 3.4 Episodic → Durable 自动总结
rollup.py 的设计——将碎片化的 episodic_memory 通过 LLM 总结为 user_profile/decision/project_memory 等持久类型——是实现"连续记忆"的核心机制。

### 3.5 前端 3D 知识图谱
Graph 页面使用 Three.js + 3d-force-graph 实现了交互式知识图谱，支持节点搜索、详情编辑、大图性能优化。

---

## 四、改进计划（分阶段）

### Phase 1：数据完整性修复（最高优先级）

| # | 任务 | 修改文件 | 预估 |
|---|------|----------|------|
| 1.1 | 持久化 curator 冷却注册表 | `storage/db.py`（新表）, `storage/curator_llm.py`（6处） | 中 |
| 1.2 | 向量同步重试队列 | `storage/db.py`（新表）, `storage/crud.py` | 中 |
| 1.3 | LLM curator 零结果诊断 | `storage/curator_llm.py`（日志）, `storage/governance.py` | 小 |

### Phase 2：LLM 治理可靠性

| # | 任务 | 修改文件 | 预估 |
|---|------|----------|------|
| 2.1 | Daemon 集成 LLM curator | `server.py`（_start_auto_curator） | 小 |
| 2.2 | LLM prompt 增加时间上下文 | `storage/curator_llm.py`（4个prompt） | 小 |
| 2.3 | LLM curator 进度追踪 | `frontend.py`, `storage/curator_llm.py` | 中 |

### Phase 3：前端重设计

| # | 任务 | 修改文件 | 预估 |
|---|------|----------|------|
| 3.1 | Dashboard 拆分为 6 个子组件 | `ui/app/page.tsx`, `ui/components/dashboard/`（新建6个） | 大 |
| 3.2 | Curator 控制移至 Governance 页 | `ui/app/governance/`（新建 CuratorRunPanel） | 中 |
| 3.3 | Governance 运行分组和依赖警告 | `ui/app/governance/components/` | 中 |

### Phase 4：高级质量功能（可选）

| # | 任务 | 修改文件 | 预估 |
|---|------|----------|------|
| 4.1 | 向量增强自动替换 | `storage/temporal_governance.py` | 小 |
| 4.2 | 复合质量评分管线 | `storage/curator.py`, `storage/dashboard.py` | 中 |
| 4.3 | 质量时间线可视化 | `frontend.py`（新端点）, `ui/components/dashboard/`（新组件） | 中 |

---

## 五、可复用的现有模式

| 模式 | 位置 | 说明 |
|------|------|------|
| Schema 迁移 | `db.py:_ensure_column()` | 向后兼容列添加 |
| MCP 工具注册 | `server.py:@mcp.tool()` | 统一工具注册模式 |
| REST API 路由 | `frontend.py:_dispatch_api()` | `parts` 匹配路由 |
| 治理管线 | `governance.py:create_governance_decision()` | 所有变更入口 |
| 批量变更 | `mutation_executor.py:execute_batch()` | 事务化批量操作 |
| i18n | `ui/hooks/useI18n()` | 中英双语 |
| Redux slice | `ui/store/*Slice.ts` | 前端状态管理 |

---

## 六、验证方案

1. **Phase 1**：运行 `python -m memorycore llm-curator --apply` 两次，第二次应跳过已审查记忆（检查 `curator_review_log` 表）
2. **Phase 2**：启动 server，临时设置 LLM curator 间隔为 5 分钟，检查 `audit_events` 中出现 `llm_curator_run` 记录
3. **Phase 3**：`npm run dev` 启动前端，验证 Dashboard 新布局，验证 /governance 页面包含 curator 控制
4. **全流程**：通过 MCP `memory_add` 添加若干语义相似记忆 → 等待/触发 LLM curator → 确认去重 decisions 出现在 /governance → apply → 确认记忆被归档
