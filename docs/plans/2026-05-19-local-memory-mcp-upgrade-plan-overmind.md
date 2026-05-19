# local-memory-mcp 升级计划书

**主题:** 借鉴 Overmind · 规避其缺陷 · 强化 lmmcp

---

## 一、现状对比

| 维度 | Overmind | local-memory-mcp（现状） |
|---|---|---|
| 存储 | SQLite FTS5 + graph.db | SQLite FTS5 + Qdrant 向量 |
| 关系图谱 | 10 种关系，自动提取 | 5 种关系，手动建边 |
| 注入机制 | 四阶段流水线，自动写 injection.md | 被动工具调用，无自动注入 |
| 预警系统 | 图谱驱动，主动检测失败模式 | 无 |
| 自进化 | Hermes Fusion，自动淘汰/晋升 | curator_report，手动触发 |
| 反馈闭环 | 注入→引用→效果全链路 | feedback_score，无闭环 |
| 技能学习 | 从对话行为自动积累偏好 | 无 |
| 跨平台 | 硬编码 D--claude 路径，实际仅 Windows | HTTP MCP，任意客户端 |
| 健壮性 | 个人项目级，多处静默失败 | 有测试套件，结构清晰 |

**结论:** Overmind 的理念领先，尤其是图谱推理、主动预警、自进化；但工程质量偏个人项目。lmmcp 工程质量更好，具备测试、模块化、HTTP MCP 和 Qdrant 混合检索，但认知能力仍偏弱。本计划将 Overmind 的认知层移植到 lmmcp 的工程底座上。

---

## 二、设计原则

### 2.1 从 Overmind 借鉴

1. 图谱是记忆的第二维度：关系比内容更有价值。
2. 注入应该是主动的，而不是完全被动等待工具调用。
3. 预警比检索更有价值：系统应帮助 Agent 阻止重蹈覆辙。
4. 反馈闭环是系统自我进化的基础。
5. 优雅降级：每层都有 fallback，不因单点失败崩溃。

### 2.2 规避 Overmind 的缺陷

1. 不硬编码路径：所有路径通过配置或环境变量注入。
2. 不误用 API Key：各服务 Key 严格隔离。
3. 不依赖平台特定启动方式，例如 `wscript.exe`。
4. 所有 schema 变更有版本管理。
5. Worker 生命周期由外部进程管理，不在应用内部自设上限。

---

## 三、升级路线图

## Phase 1：知识图谱增强（2 周）

**目标:** 将现有 5 种关系扩展为 10 种，并实现自动关系提取。

### 1.1 扩展关系类型

现有 `memory_links` 表的 `relation_type` 已有约束，需扩展：

```python
# models.py — 扩展 VALID_RELATION_TYPES
VALID_RELATION_TYPES = {
    "related_to",      # 现有
    "supersedes",      # 现有
    "contradicts",     # 现有
    "supports",        # 现有
    "part_of",         # 现有
    # 新增
    "depends_on",      # A 依赖 B 才能运行
    "blocked_by",      # A 被 B 阻塞（触发预警）
    "causes",          # A 导致 B（配合反馈触发失败模式预警）
    "solves",          # A 解决了 B
    "triggers",        # A 激活 B
}
```

迁移脚本：

```sql
-- migration_001_relation_types.sql
-- 无需修改表结构，relation_type 是 TEXT 字段
-- 仅更新 models.py 中的约束集合
-- 版本记录：
INSERT OR IGNORE INTO schema_versions(version, applied_at)
VALUES ('001', datetime('now'));
```

### 1.2 Schema 版本管理表

```sql
CREATE TABLE IF NOT EXISTS schema_versions (
  version TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL,
  description TEXT DEFAULT ''
);
```

在 `init_db()` 中加入，所有后续 migration 通过此表追踪。

### 1.3 自动关系提取工具

新增 MCP 工具 `memory_extract_relations`：

```python
# server.py 新增工具
@mcp.tool()
def memory_extract_relations(
    conversation: list[dict],  # [{"role": "user/assistant", "content": "..."}]
    source_agent: str = "agent",
) -> dict:
    """从对话中自动提取记忆间关系，写入 memory_links。"""
```

实现逻辑（`extraction.py` 扩展）：

1. 获取当前所有 active 记忆的 id + title，最多 200 条。
2. 构造提取 prompt，要求 LLM 输出：

```json
[
  {
    "source_id": "...",
    "target_id": "...",
    "relation_type": "...",
    "confidence": 0.8,
    "evidence": "..."
  }
]
```

3. `confidence >= 0.5` 的关系写入 `memory_links`，使用 upsert 语义。
4. 返回提取数量和关系列表。

Fallback：LLM 超时或失败时，基于 title 关键词重叠做简单 `related_to` 连边。

---

## Phase 2：主动预警系统（1.5 周）

**目标:** 实现 Overmind 的 Proactive Guard，在 `memory_context` 中自动附加危险信号。

### 2.1 预警检测逻辑

新增 `storage.py` 函数 `get_warnings(memory_ids, limit=5)`：

```python
def get_warnings(memory_ids: list[str], limit: int = 5) -> list[dict]:
    """
    检测危险信号：
    1. blocked_by 关系 → ⚠️ 阻塞风险
    2. conflicts_with/contradicts 关系 → ⚡ 潜在冲突
    3. causes 关系 + 目标记忆 feedback_score < -0.5 → 🔴 失败模式
    4. 自身 feedback_score < -1.0 且被访问 ≥ 3 次 → 🟡 低效记忆
    """
```

实现示例：

```python
def get_warnings(memory_ids: list[str], limit: int = 5) -> list[dict]:
    if not memory_ids:
        return []
    warnings = []
    with managed_conn() as conn:
        placeholders = ",".join("?" * len(memory_ids))
        edges = conn.execute(f"""
            SELECT l.*,
                   sm.title as source_title, sm.feedback_score as source_fb,
                   tm.title as target_title, tm.feedback_score as target_fb
            FROM memory_links l
            JOIN memories sm ON l.source_id = sm.id
            JOIN memories tm ON l.target_id = tm.id
            WHERE (l.source_id IN ({placeholders}) OR l.target_id IN ({placeholders}))
              AND l.relation_type IN ('blocked_by','contradicts','conflicts_with','causes')
        """, memory_ids * 2).fetchall()

        for e in edges:
            e = dict(e)
            if e["relation_type"] == "blocked_by":
                warnings.append({
                    "type": "blocked",
                    "severity": "high" if e["weight"] >= 0.7 else "medium",
                    "label": "⚠️ 阻塞风险",
                    "reason": f"{e['source_title']} 被 {e['target_title']} 阻塞",
                    "source_id": e["source_id"],
                    "target_id": e["target_id"],
                })
            elif e["relation_type"] in ("contradicts", "conflicts_with"):
                warnings.append({
                    "type": "conflict",
                    "severity": "medium",
                    "label": "⚡ 潜在冲突",
                    "reason": f"{e['source_title']} 与 {e['target_title']} 存在冲突",
                    "source_id": e["source_id"],
                    "target_id": e["target_id"],
                })
            elif e["relation_type"] == "causes" and float(e["target_fb"] or 0) < -0.5:
                warnings.append({
                    "type": "failure_pattern",
                    "severity": "high",
                    "label": "🔴 失败模式",
                    "reason": f"{e['source_title']} 曾导致 {e['target_title']} 失败",
                    "source_id": e["source_id"],
                    "target_id": e["target_id"],
                    "feedback_score": e["target_fb"],
                })

    with managed_conn() as conn:
        placeholders = ",".join("?" * len(memory_ids))
        low = conn.execute(f"""
            SELECT id, title, feedback_score, last_accessed_at
            FROM memories
            WHERE id IN ({placeholders})
              AND feedback_score < -1.0
              AND last_accessed_at IS NOT NULL
        """, memory_ids).fetchall()
        for r in low:
            warnings.append({
                "type": "ineffective",
                "severity": "medium",
                "label": "🟡 低效记忆",
                "reason": f"记忆「{r['title']}」反馈分数 {r['feedback_score']:.1f}，持续无效",
                "source_id": r["id"],
                "target_id": r["id"],
            })

    severity_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(warnings, key=lambda w: severity_order.get(w["severity"], 2))[:limit]
```

### 2.2 集成到 build_context_pack

在 `build_context_pack` 返回结果中增加 `warnings` 字段：

```python
# build_context_pack 末尾
warnings = get_warnings(used_ids)
if warnings:
    warning_lines = ["## ⚠️ 危险信号", ""]
    for w in warnings:
        warning_lines.append(f"### {w['label']}")
        warning_lines.append(w["reason"])
        warning_lines.append("")
    text = "\n".join(warning_lines) + "\n---\n" + text

return {
    "context": text,
    "warnings": warnings,
    # ... 其余字段不变
}
```

### 2.3 新增独立 MCP 工具

```python
@mcp.tool()
def memory_search_warnings(
    memory_ids: list[str],
    limit: int = 5,
) -> dict:
    """检测指定记忆集合的危险信号（阻塞、冲突、失败模式）。"""
    warnings = get_warnings(memory_ids, limit)
    return {"warnings": warnings, "count": len(warnings)}
```

---

## Phase 3：反馈闭环强化（1 周）

**目标:** 将现有的单次 `feedback_score` 升级为全链路追踪：注入→引用→效果。

### 3.1 扩展 feedback_events 表

```sql
-- migration_002_feedback_events.sql
ALTER TABLE feedback_events ADD COLUMN event_type TEXT DEFAULT 'manual';
-- event_type: manual | injected | referenced | helped | ineffective
ALTER TABLE feedback_events ADD COLUMN session_id TEXT DEFAULT '';
ALTER TABLE feedback_events ADD COLUMN context TEXT DEFAULT '';
```

### 3.2 注入事件追踪

在 `build_context_pack` 中，每次生成上下文时自动记录 `injected` 事件：

```python
session_id = f"ctx_{int(datetime.now().timestamp())}"
for mid in used_ids:
    add_feedback(
        mid,
        score=0.0,
        note="injected",
        source_agent=agent,
        event_type="injected",
        session_id=session_id,
    )
```

### 3.3 引用检测工具

新增 `memory_record_usage` 工具，供 consolidate 阶段调用：

```python
@mcp.tool()
def memory_record_usage(
    memory_ids: list[str],
    outcome: str,  # "helped" | "ineffective" | "referenced"
    session_id: str = "",
    source_agent: str = "agent",
) -> dict:
    """记录一批记忆在本次会话中的实际效果。"""
    score_map = {"helped": 1.0, "referenced": 0.5, "ineffective": -0.5}
    score = score_map.get(outcome, 0.0)
    results = []
    for mid in memory_ids:
        result = add_feedback(
            mid,
            score=score,
            note=outcome,
            source_agent=source_agent,
            event_type=outcome,
            session_id=session_id,
        )
        results.append(result)
    return {"recorded": len(results), "outcome": outcome}
```

### 3.4 效果排序

在 `search_memory_records` 的排序中加入 feedback 权重：

```sql
-- 现有排序
ORDER BY m.importance DESC, m.feedback_score DESC, m.updated_at DESC

-- 升级后：综合有效率排序
ORDER BY (
  m.importance * 0.4 +
  CASE
    WHEN m.feedback_score > 0 THEN m.feedback_score * 0.4
    ELSE m.feedback_score * 0.2
  END +
  0.2 * (julianday('now') - julianday(m.updated_at)) * -0.01
) DESC
```

---

## Phase 4：自动 Consolidate 增强（1 周）

**目标:** 将现有的手动 curator 升级为具备 AI 辅助的自进化系统，同时保持 dry_run 安全性。

### 4.1 AI 辅助去重合并

在 `curator_report` 中，对 `duplicate_title_groups` 调用 LLM 判断是否真正重复：

```python
# extraction.py 新增
async def ai_dedup_judge(group: list[dict], api_key: str) -> dict:
    """
    输入：同 title_key 的多条记忆
    输出：{"action": "merge|keep_all|mark_stale", "keep_id": "...", "reason": "..."}
    """
    prompt = f"""以下记忆标题相似，判断是否重复：
{json.dumps([
    {"id": r["id"], "title": r["title"], "content": r["content"][:200]}
    for r in group
], ensure_ascii=False, indent=2)}

输出 JSON：{{"action": "merge|keep_all|mark_stale", "keep_id": "<保留的id>", "reason": "<原因>"}}
- merge: 内容实质相同，保留最新，其余标记 contradicted
- keep_all: 内容不同，都有价值
- mark_stale: 旧版本，标记为 stale"""
    # 调用 DeepSeek flash（低成本）
    ...
```

### 4.2 技能候选自动晋升

扩展 `curator_report` 的 `skill_promotion_candidates` 处理：

```python
for r in skill_promotion_candidates:
    if float(r.get("feedback_score", 0)) >= 0.5 and float(r.get("importance", 0)) >= 0.7:
        update_status(r["id"], "promoted")
        actions.append({"id": r["id"], "action": "promote_skill", "title": r.get("title")})
```

### 4.3 衰减策略执行

新增 `apply_decay` 函数，在 curator 中调用：

```python
def apply_decay(dry_run: bool = True) -> list[dict]:
    """
    衰减规则：
    - 30 天未访问 + importance < 0.5 → confidence -= 0.1
    - 60 天未访问 + feedback_score <= 0 → status = stale
    - stale 超过 120 天 → status = archived
    """
```

---

## Phase 5：图谱扩展注入（1 周）

**目标:** 在 `memory_context` 中，选中的记忆自动沿图谱扩展关联节点，实现 Overmind 的联想检索。

### 5.1 图谱扩展函数

```python
# storage.py 新增
def expand_by_links(
    memory_ids: list[str],
    depth: int = 1,
    relation_filter: list[str] | None = None,
    limit: int = 10,
) -> dict:
    """
    从 memory_ids 出发，沿 memory_links 扩展 depth 层。
    返回扩展后的 memory_ids 集合和关系子图。
    """
    visited = set(memory_ids)
    frontier = list(memory_ids)
    edges_found = []

    for _ in range(depth):
        if not frontier:
            break
        placeholders = ",".join("?" * len(frontier))
        rel_filter = ""
        params = list(frontier) * 2
        if relation_filter:
            rel_filter = f" AND relation_type IN ({','.join('?' * len(relation_filter))})"
            params += relation_filter * 2

        with managed_conn() as conn:
            rows = conn.execute(f"""
                SELECT source_id, target_id, relation_type, weight, note
                FROM memory_links
                WHERE (source_id IN ({placeholders}) OR target_id IN ({placeholders}))
                {rel_filter}
                ORDER BY weight DESC
            """, params).fetchall()

        next_frontier = []
        for r in rows:
            edges_found.append(dict(r))
            for nid in (r["source_id"], r["target_id"]):
                if nid not in visited:
                    visited.add(nid)
                    next_frontier.append(nid)
        frontier = next_frontier[:limit]

    return {
        "expanded_ids": list(visited),
        "new_ids": [i for i in visited if i not in set(memory_ids)],
        "edges": edges_found,
    }
```

### 5.2 集成到 build_context_pack

```python
expansion = expand_by_links(
    used_ids,
    depth=1,
    relation_filter=["depends_on", "part_of", "solves", "blocked_by"],
)
if expansion["new_ids"]:
    extra_records = [get_record(mid) for mid in expansion["new_ids"][:5] if get_record(mid)]
    records = records + [r for r in extra_records if r and r not in records]
```

---

## Phase 6：Context Pack 自动注入（可选，2 周）

**目标:** 实现类 Overmind 的自动注入，但以 lmmcp 的方式：通过 Hook 写入 `injection.md`，供 include 读取。

与 Overmind 的关键区别：

- 路径通过 `config.yaml` 配置，不硬编码。
- 支持多平台，例如 Claude Code、Cursor、Codex。
- Worker 作为独立进程，由 systemd/launchd 管理，不自设生命周期上限。

### 6.1 配置扩展

```yaml
# config.yaml 新增
injection:
  enabled: false          # 默认关闭，用户主动开启
  output_path: ""         # 空 = 不写文件，由调用方决定
  transcript_dir: ""      # 空 = 不读 transcript，依赖 MCP 工具调用
  auto_worker: false      # 是否启动后台 Worker
  worker_interval: 30     # Worker 轮询间隔（秒）
  api_key_env: "DEEPSEEK_API_KEY"  # 明确指定，不 fallback 到其他 Key
```

### 6.2 注入脚本

```python
# inject.py（新文件，独立于 MCP server）
"""
独立注入脚本，可由 Claude Code Hook 调用：
  python inject.py  →  写入 config.injection.output_path
"""
```

四阶段流水线，与 Overmind 相同逻辑，但基于 lmmcp 的存储层：

- Phase 0：本地图谱预警，0ms，无 API。
- Phase 1：关键词检索，写 lite 版本。
- Phase 2：并行 AI 精选，记忆 + 技能。
- Phase 3：图谱扩展 + 反馈排序，写 full 版本。

---

## 四、新增 MCP 工具汇总

| 工具 | 阶段 | 用途 |
|---|---|---|
| `memory_extract_relations` | Phase 1 | 从对话自动提取关系边 |
| `memory_search_warnings` | Phase 2 | 检测危险信号 |
| `memory_record_usage` | Phase 3 | 记录记忆使用效果 |
| `memory_expand_links` | Phase 5 | 图谱扩展检索 |
| `memory_apply_decay` | Phase 4 | 执行衰减策略 |

现有工具增强：

- `memory_context`：增加 `warnings` 字段 + 图谱扩展。
- `memory_curator_report`：增加 AI 辅助去重判断。
- `memory_link_add`：支持新增 5 种关系类型。

---

## 五、风险规避清单

| Overmind 的问题 | lmmcp 的对策 |
|---|---|
| `TRANSCRIPT_DIR` 硬编码 | `config.yaml` 的 `injection.transcript_dir`，空值时禁用 Worker |
| `ANTHROPIC_AUTH_TOKEN` 误用为 DeepSeek Key | `config.yaml` 明确 `api_key_env` 字段，各服务 Key 严格隔离，启动时校验 |
| Worker 8h 生命周期上限 | Worker 作为独立进程，生命周期由 systemd/launchd 管理 |
| `wscript.exe` 平台锁定 | Python subprocess 跨平台，或直接 `python -m local_memory_mcp worker` |
| 无 schema 版本管理 | `schema_versions` 表，所有 migration 有版本号 |
| AI 幻构关系无审核 | `confidence < 0.5` 的关系不写入；提供 dry_run 模式预览 |
| 注入时序竞争 | 文件锁 `fcntl.flock` + 原子 rename，使用 Python 实现 |
| 技能偏好归一化过激 | 不截断 `task_scenario`，保留原始描述，搜索时做模糊匹配 |
| 情景摘要来源循环依赖 | 摘要从原始 transcript 生成，不从 `injection.md` 生成 |

---

## 六、实施优先级

| 时间 | 阶段 | 内容 |
|---|---|---|
| Week 1-2 | Phase 1 | 图谱关系扩展 + schema 版本管理 |
| Week 3-4 | Phase 2 | 预警系统 + 集成到 `memory_context` |
| Week 5 | Phase 3 | 反馈闭环强化 |
| Week 6 | Phase 4 | 自动 Consolidate + AI 去重 |
| Week 7 | Phase 5 | 图谱扩展注入 |
| Week 8+ | Phase 6 | 自动注入，可选，按需启用 |

每个 Phase 完成后：

1. 更新对应测试，例如 `tests/test_*.py`。
2. 更新 `schema_versions` 表。
3. 更新 `config.yaml` 文档注释。
4. 运行 `.venv/bin/python -m pytest -q` 确认无回归。

---

## 七、核心设计决策

### 为什么不直接用 Overmind 的 graph.js？

lmmcp 已有 `memory_links` 表，结构更规范：有 FK 约束、唯一索引、weight 字段。Overmind 的 `graph.db` 是独立 SQLite，与记忆库分离，导致 JOIN 困难。将图谱合并到同一个 SQLite 库，查询效率更高，事务一致性更强。

### 为什么保留 Qdrant 而不用 Overmind 的 FTS5 only？

Qdrant 的语义搜索能处理跨语言，例如中文查询匹配英文记忆，也能处理同义词匹配，这是 FTS5 bigram 做不到的。两者互补：FTS5 做精确关键词，Qdrant 做语义相似，`memory_smart_search` 已经实现混合检索。

### 为什么预警系统基于 memory_links 而不是独立 graph.db？

统一存储带来事务一致性，避免 Overmind 中图谱与记忆库不同步的问题。代价是图遍历性能略低，但在记忆规模小于 10k 条时不是瓶颈。

---

## 八、与现有文档的关系

本计划与以下文档互补：

- `docs/plans/2026-05-19-overmind-lessons-lmmcp-hardening.md`：偏防错与安全加固。
- `docs/plans/2026-05-19-overmind-inspired-lmmcp-evolution.md`：偏产品能力演进。
- `docs/plans/2026-05-19-agent-memory-hook-contract.md`：偏跨 Agent Hook / Wrapper / MCP 协议。

本计划更偏实施路线图，重点是阶段、工具、schema、函数与优先级。
