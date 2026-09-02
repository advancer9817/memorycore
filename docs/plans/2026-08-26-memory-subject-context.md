# 记忆主体上下文缺失 — 详细设计与迭代方案

> 日期：2026-08-26
> 状态：**已实施（2026-09-02，[迭代 211]）** — P1/P2/P3 最小闭环 + P5 存量回填已落地；P4 检索端扩展留待后续。原编号迭代 33 → 重排后迭代 196。
> 关联：`docs/plans/2026-08-24-unified-iteration-plan.md`（统合版）、`memorycore/storage/context_pack.py`（检索端）、`memorycore/extraction.py`（提取端）
> 作者：Hermes Agent（default router）

---

## 0. 背景与问题（量化基线）

用户在 mcore 记忆库中发现：提取出的单条记忆缺乏「主体」锚点。例如截图中的「迭代 31」「迭代 27」等记录，全文不提 `mcore`，单条脱离 UI 后无法判断这是哪个项目的迭代。

实测真实库（2026-08-26，memories 8399 条）：

| 指标 | 数值 | 结论 |
|---|---|---|
| 标题含「迭代」的记录 | 189 条 | 截图所指类别 |
| 其中 title+content **均无** mcore/memorycore | **110 条（58%）** | 无头记录，主体缺失 |
| `project_path` 为空 | **7976 / 8399（95%）** | 主体字段几乎全空 |
| `scope` = `global` | 8304 条（99%） | 无项目边界 |
| `source_agent` 分布 | claude 2503 / frontend 2230 / hermes 1272 / … | 记录的是「谁写的」，非「关于谁」 |

**影响（三层检索均受损）：**
1. **FTS5（关键词）**：搜「mcore 迭代」→ 记录文本无 `mcore` token → 直接 miss（最硬损失）。
2. **向量（语义）**：搜「mcore 项目进度」→ 无 `mcore` 锚点，embedding 相似度被稀释。
3. **实体检索**：`memory_entity_search("mcore")` 依赖 `memory_entities` 表，而实体只从文本抽——文本无 `mcore` 即无实体行 → 捞不到。

---

## 1. 根因链

```
提取 prompt 有「自包含」规则
   └─ 但 _build_user_prompt 只喂 messages + existing_memories，
      没告诉 LLM「这段对话发生在 mcore 项目」→ LLM 无从下笔
          └─ 落库时 ingest 只写 source_agent=agent_id（谁写的），
             project_path 压根没传 → 95% 为空
                └─ 实体索引只从 title+content 抽，
                   文本无 mcore → 无实体行 → 确定性检索失效
```

**关键发现：检索端管线已经全部接好。** `context_pack.build_context_pack`、`entity_search`、`search._search_memory_records`、`rollup` 均已把 `project_path` / `scope` 透传到查询；`add_memory_record` 也早已接受 `project_path` 参数。**唯一缺口在写入侧**：`dedup.ingest()` 不传 `project_path`、`memory_ingest()` 不暴露、hook `mcore-ingest.py` 不发送。因此本方案的核心是「接通管线 + 提取期注入 + 实体兜底」，而非重写检索。

---

## 2. 方案总览（五阶段）

| 阶段 | 对应建议 | 目标 | 优先级 | 预估工作量 |
|---|---|---|---|---|
| P1 提取期注入主体 | ① | LLM 知道项目名，写出带主体的自包含事实 | **P0** | 0.5 天 |
| P2 ingest 落库 metadata | ② | `project_path`/`scope`/`project:*` 标签结构化落库 | **P0** | 0.5 天 |
| P3 实体索引兜底 | ③ | 项目实体确定性注入，`entity_search("mcore")` 100% 命中 | **P0** | 0.5 天 |
| P4 检索端主体扩展 | ④ | 查询期项目名自动扩展 + 自动探测 project_path | P1 | 0.5 天 |
| P5 存量回填 | ⑤ | 8399 条存量补主体标签（治标救急） | P2（可选） | 1 天 |

> P1+P2+P3 是一个连贯的最小闭环：**提取知道主体 → 落库存主体 → 检索捞主体**。三者一起改完，新数据自愈、旧数据靠 P3 兜底召回。

---

## 3. 详细设计

### P1 — 提取期注入主体上下文（`memorycore/extraction.py`）

**目标**：让提取 LLM 明确知道「当前对话主体」，从而把「迭代 31」写成「mcore 迭代 31」。

1. `ExtractedFact` dataclass 新增字段：
   - `subject: str = ""`（LLM 标注的规范项目名）
   - `entities: list[str] = field(default_factory=list)`（LLM 标注的实体列表）

2. `extract_facts(...)` 新增参数：
   - `project_path: str = ""`
   - `project_name: str = ""`
   - `scope: str = "global"`

3. `_build_user_prompt(...)` 注入「Active Context」段：
   ```
   ## Active Context（当前对话主体）
   - project_name: mcore          # 空串表示未知
   - project_path: /home/advancer/project/memorycore
   - scope: project
   ```
   仅当 `project_name` 非空时注入；`project_name` 由 `project_path` 经配置白名单/别名表解析（见 §4 配置）。

4. `ADDITIVE_EXTRACTION_PROMPT` 强化：
   - **规则 2（自包含）追加**：若 Active Context 提供了 `project_name`，且事实属于该项目，则 `title` 必须以 `<project_name> ` 为前缀（如 `mcore 迭代31 …`），或 `content` 明确包含项目名。
   - **输出 schema 追加**：每条 fact 可带 `"subject"`（规范项目名，可选）与 `"entities"`（实体数组，可选）。
   - **示例追加**：一个「mcore 迭代」的正反例。

5. `_parse_response(...)` 解析 `subject` / `entities` 进 `ExtractedFact`。

### P2 — ingest 落库 metadata（`memorycore/dedup.py` + `server.py` + hook）

**目标**：把主体信息结构化写入 `project_path` / `scope` / tags。

1. `dedup.ingest(...)` 新增参数 `project_path: str = ""`、`scope: str = "global"`：
   - `mem_scope = scope or es.get("default_scope", "global")`
   - 把 `project_path` / `project_name` 传入 `extract_facts(...)`（P1）。
   - 在 `_add_memory_fn(...)` 调用（`add` 分支，约 line 472）补 `project_path=project_path`、`scope=mem_scope`。
   - tags 追加 `project:<name>`（当 `project_name` 非空）；`metadata` 追加 `subject`（取 fact.subject 或 project_name）。

2. `server.memory_ingest(...)` 新增 `project_path` / `scope` 参数，透传给 `ingest()`。

3. `scripts/hooks/mcore-ingest.py`：
   - 新增 `_detect_project(agent, cwd)` 辅助函数：
     - claude：从 transcript 路径 `~/.claude/projects/<slug>/` 取 slug；
     - 其他：`git -C <cwd> rev-parse --show-toplevel` 或环境变量 `MCORE_PROJECT_PATH`；
     - 最终经配置 `projects` 白名单 → 规范 `project_name` + `scope`。
   - `_ingest(messages, agent_id, project_path="", scope="global")` 把这两个值塞进 `memory_ingest` 的 `arguments`。

### P3 — 实体索引兜底（`memorycore/storage/entities.py`）

**目标**：即便 LLM 没写对项目名，`entity_search("mcore")` 也能确定性命中所有 mcore 记录。

1. 新增 `resolve_project_entity(project_path) -> dict | None`：把路径经配置 `projects` 白名单 + 现有 `_ALIAS_GROUPS` 别名表映射为规范项目实体（含 aliases、weight=1.0、entity_type="concept"）。

2. `sync_memory_entities(record, ...)`：在从文本抽出的实体之外，若 `record.project_path`（或 `metadata.subject`）能解析出项目实体，且文本实体中不含它，则**强制注入该实体行**。这样每条 mcore 项目记录都会带 `mcore` 实体行，检索确定性生效。

3. 保持 `status != active` 时清空实体行的既有行为不变。

### P4 — 检索端主体扩展（`memorycore/storage/context_pack.py` + 调用方）

**目标**：查询期自动带上项目名 / 自动探测项目路径。

1. `build_context_pack` 已透传 `project_path`/`scope`，无需改动核心。补充：
   - 当 `project_name` 已知且 `project_path` 非空时，可选地将项目名作为低权重 query 扩展注入 FTS/向量召回（guard 保护，避免污染 query）。
   - 当 `project_path` 为空时，调用方自动探测：`git rev-parse --show-toplevel` → 解析项目名。

2. 调用方（Hermes `memory_context` 插件 / hook）：把探测到的 `project_path`/`scope` 传进 `build_context_pack`（当前 Hermes 调用为 `project_path: (none)`，需补上）。

> P4 依赖 P1-P3 已落地；是增强项，非闭环必需。

### P5 — 存量回填（可选，一次性脚本）

**目标**：给 8399 条存量补主体，立刻改善现状。

- 新增 `scripts/backfill_subject.py`（dry-run 默认，`--apply` 才写）：
  1. 高置信：`content`/`title` 明确含 `mcore|memorycore|qdrant|8318|18318|nomic-embed-text|memory.sqlite3|迭代` 等强信号（≥2 个或显式 mcore 提及）→ 写 `project_path` + `project:mcore` 标签 + `scope=project`。
  2. 低置信：仅 1 个弱信号 → 打 `needs_review` 元数据，不自动改主体，交治理面板人工确认。
  3. 输出 `plan`（命中计数 + 分桶 + protected 说明），执行前强制备份（复用 clean 的备份/幂等链路）。
- 事后 `memory_rebuild_vectors` 同步 Qdrant payload + 重建实体索引。

---

## 4. 配置变更（`config.yaml`）

新增 `subject_context` 段（进程启动读取，改动需重启，见 mcore-operations pitfall 13）：

```yaml
subject_context:
  enabled: true
  default_scope: global          # 无项目信号时的兜底
  projects:
    - name: mcore                # 规范项目名（实体 + 标签 + 标题前缀）
      paths: ["/home/advancer/project/memorycore"]
      aliases: ["memorycore", "MemoryCore"]
      scope: project
  # 未来可扩展：千帆 / CPA 等其他项目
```

`extraction_strategy.default_scope: global` 保持，P2 用 `subject_context` 的 `default_scope` 覆盖。

---

## 5. 数据流（前后对比）

```
【改造前】
hook(mcore-ingest) ──messages+agent_id──▶ memory_ingest ──▶ ingest ──▶ add_memory_record(无 project_path)
        ↓                                                          ↓
  提取 prompt（无主体上下文）                            project_path="" scope=global
        ↓                                                          ↓
  LLM 输出「迭代31:…」                                  实体索引无 mcore 行 → 检索 miss

【改造后】
hook ──messages+agent_id+project_path+scope──▶ memory_ingest ──▶ ingest ──▶ add_memory_record(project_path+scope+project:*)
        ↓（提取期注入 Active Context）                            ↓
  LLM 输出「mcore 迭代31:…」+ subject=mcore          project_path=… scope=project
        ↓                                                          ↓
  FTS/向量可命中「mcore」                      实体索引强制注入 mcore → entity_search 100% 命中
```

---

## 6. 测试计划

| 用例 | 断言 |
|---|---|
| P1 提取 | 给定带 Active Context 的对话 → LLM 输出 title 以 `mcore ` 前缀 / content 含项目名；`_parse_response` 解析出 `subject` |
| P2 落库 | `ingest(project_path=…, scope="project")` → 新记录 `project_path` 非空、`scope=project`、tags 含 `project:mcore` |
| P3 实体 | 记录无文本实体但有 project_path → `sync_memory_entities` 注入 mcore 实体行；`entity_search("mcore")` 命中 |
| P4 检索 | `build_context_pack(task, project_path=…)` 过滤/扩展生效 |
| P5 回填 | dry-run 计数正确；高置信命中被标注、低置信进 review；`--apply` 幂等（重复跑不重复写） |
| 回归 | 全量 pytest 通过；既有 D2/D3/curator 用例不回归 |

---

## 7. 验收标准

1. 新提取的 mcore 迭代类记忆，`title` 或 `content` 含 `mcore`（抽检 ≥90%）。
2. 新记录 `project_path` 非空、`scope` 正确、tags 含 `project:*`。
3. `memory_entity_search("mcore")` 能确定性命中所有 project_path=mcore 的记录（含存量 P3 兜底）。
4. `memory_context` 在 mcore 项目目录运行时，`project_path` 自动探测成功（不再 `(none)`）。
5. 全量测试通过，无安全/治理回归。

---

## 8. 风险与回滚

| 风险 | 缓解 | 回滚 |
|---|---|---|
| 提取 prompt 改动导致事实质量下降 | 单测 + 抽检对比改前/改后提取结果；`subject_context.enabled=false` 可整体关闭 | 还原 extraction.py + 重启 |
| 项目探测误判（cwd 非项目 / 多项目对话） | 白名单命中才设 scope=project；无信号回落 global；LLM 仍可逐条标 subject | 还原 hook + config |
| P5 回填误标注 | dry-run 先行 + 强信号门槛 + 低置信进 review 不自动改 | 依赖 clean 的备份链路可恢复 |
| 存量 Qdrant/实体索引不同步 | 回填后 `memory_rebuild_vectors` + 重建实体索引 | — |

---

## 9. 迭代拆分（映射 ITERATION.md）

| 迭代 | 范围 | 阶段 |
|---|---|---|
| **迭代 33** | P1+P2+P3 最小闭环 + 配置 + 单测 | 本次规划 |
| 迭代 34（可选） | P4 检索端扩展 + 调用方自动探测 | 后续 |
| 迭代 35（可选） | P5 存量回填脚本 + 治理面板 review 入口 | 后续 |
