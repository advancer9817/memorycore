# mcore llm-curator 资源占用 — 系统审查报告（审计纠正版）

> 状态：审查完成，纠正前序两份文档的根因诊断
> 创建：2026-08-17
> 前序文档：
> - `docs/2026-08-17-llm-curator-resource-optimization.md`（原始调查 + P0/P1/P2 方案清单）
> - `docs/2026-08-17-llm-curator-resource-optimization-execution.md`（Round 2 执行交接）
> 结论：**两份文档的根因诊断均建立在错误前提上；真正的问题另有出处。** 本报告给出证据并重新定位问题。
> 项目：/home/advancer/project/memorycore

---

## 1. 摘要

针对「`llm-curator` 运行期间主服务 `mcore.service`（:8318）API 变慢（`/api/v1/stats` 43s、`memory_add` MCP 120s 超时）」这一现象，对 `memorycore` 代码做了逐行核查。核心结论：

1. **「全量 rebuild 每轮 embed 5000 条」不成立** —— `memory_rebuild_vectors()` 被以默认 `dry_run=True` 调用，从未真正重建，实测 `rebuilt: 0`。
2. **「curator 变更链路完全不碰 Qdrant」不成立** —— 增量同步（`_sync_results` / `update_status_batch` → `_sync_to_vector`）早已接好。
3. 因此前序文档的「方案 B（关 rebuild + 增量同步）」与「P0-1」落空：关的是一个本就什么都不做的 dry-run，而它要新增的增量同步已经存在。
4. 真正的性能/正确性问题在别处，按严重度见第 3 节（P0-1 同步 embed 洪流、P0-2/P0-3 静默降级等）。

---

## 2. 前序文档的证伪证据

### 2.1 rebuild 一直是 dry-run，零 embed

- `memorycore/storage/transfer.py:335` 签名：`memory_rebuild_vectors(dry_run: bool = True, limit: int = 5000)`，`dry_run` **默认 `True`**。
- `transfer.py:345-346`：`if dry_run: return {"dry_run": True, "planned": len(rows), "rebuilt": 0}` —— 直接返回计数，**不 embed 任何一条**。
- 两个调用点都**不传参数**（走默认 dry-run）：
  - `memorycore/storage/curator_llm/report.py:431`：`report = {**report, "rebuild_vectors": memory_rebuild_vectors()}`
  - `memorycore/storage/curator_llm/report.py:388`：`memory_rebuild_vectors()`

实测（`reports/llm-curator-20260817T010800Z.json`）：

```json
"rebuild_vectors": {"dry_run": true, "planned": 2136, "rebuilt": 0}
```

`planned: 2136`、`rebuilt: 0`。所谓「5000 次/轮的 embed 洪流」**在运行时并不存在**。

### 2.2 增量同步早已存在

Round 2 文档「★核心发现」称 curator 的 archive/supersede/contradicted/split 变更「完全不碰 Qdrant，全靠最后那轮全量 rebuild 冲刷」。代码实况：

- `memorycore/storage/mutation_executor.py:166`：`execute_batch` 末尾调用 `_sync_results(results)`。
- `mutation_executor.py:457-465`：`_sync_results` 对每个 `mutation_type.startswith("memory")` 且带 `after.id` 的结果调 `_sync_record_indexes(after)` → `_sync_to_vector`。
- `memorycore/storage/governance_ops.py:427`：`apply_governance_decisions_batch` 在事务外显式 `_sync_results(results)`。
- 规则 curator：`memorycore/storage/curator.py:361` → `update_status_batch` → `memorycore/storage/crud.py:378-397` 对每条 status 变更调 `_sync_record_indexes`。

对应语义（`crud.py:46-87` `_sync_to_vector`）：archive/supersede/contradicted → `vs.delete()`；split 子记忆（active）→ `vs.upsert()`（异步）。**这条链路已经在跑。**

### 2.3 结论修正对照

| 前序文档结论 | 审查结果 |
|---|---|
| 全量 rebuild 每轮 embed 5000 条，是性能罪魁 | ❌ 假。rebuild 是 dry-run，`rebuilt: 0`，零 embed |
| curator 变更链路完全不碰 Qdrant | ❌ 假。`_sync_results` / `update_status_batch` 已做增量同步 |
| rebuild 是唯一同步 Qdrant 的正确性兜底 | ❌ 假。它既不 rebuild（dry-run），也不 delete stale |
| 方案 B「关 rebuild + 增量同步」 | ⚠️ 增量同步已存在、关 rebuild 是无效开关，整体落空 |
| P0-2 / P0-3 systemd 降级调度 | ✅ 仍有效（独立于上述结论） |

---

## 3. 已确认的真实问题（按严重度）

### 🔴 P0-1：`memory_add` 超时的真正根因 —— `process_auto_supersession` 的同步 embed 洪流

文档把 `memory_add` 的 120s 超时归因于 rebuild。真实机制是 `add_memory_record` 末尾**同步**调用 `process_auto_supersession`，其内部对每条候选记录做一次向量检索（每次 = 1 次 Ollama embed + 1 次 Qdrant 查询）：

- `crud.py:284-287`：`add_memory_record` 每次都调 `process_auto_supersession(result, source_agent=...)`。
- `memorycore/storage/temporal_governance.py:105-126` `_candidate_rows`：取同 `type+scope+project_path` 的 active 候选，`LIMIT 50`。
- `temporal_governance.py:146-149`：对**每一条**候选调 `_similarity` → `_vector_similarity`（`temporal_governance.py:62`）→ `vs.search(query_text, top_k=50)`。
- 这些调用都在 `memory_add` 的**同步请求路径**上，与 `_sync_to_vector` 的 fire-and-forget 线程不同。

后果：一次 `memory_add` 最多触发 **50 次同步 embed**。当 Ollama 被 curator 的候选扫描占满时，每次 embed 阻塞到 `embedding.timeout=30s`（`config.yaml:17`），50 × 30s 远超 120s。**这才是 `memory_add` 120s 超时的直接机制。**

### 🔴 P0-2：`embed_text` 静默降级到 hashing，污染向量索引

`memorycore/vector_store.py:139-186`：`provider: auto` 下，Ollama 一旦失败即 fallback 到 `_embed_hashing`（`:303-314`，确定性伪随机向量），并**正常返回、正常 upsert**，只打 warning。

后果：Ollama 被占满/宕机时（恰好就是 curator 运行期间），新写入的记忆拿到与 collection 里真实 nomic 向量**维度分布无关**的 hashing 向量，语义检索从此对这条记录失配。这是**静默的、持久的数据损坏**，不是临时降级。

### 🔴 P0-3：`VectorStore` 故障后 30s 冷却 + 静默空结果

`vector_store.py:381-383`：init 失败后 30s 冷却；期间 `search()` 返回 `[]`（`:485-486`）、`upsert()` 返回 `False`（`:436`）。

后果：`memory_context` / `memory_vector_search` / `process_auto_supersession` 均**无异常抛出**，调用方拿到「没有相关记忆」而非「服务不可用」。检索侧静默失败，调用方无感知。

### 🟠 P1-1：`_sync_to_vector` status 语义与 curator 检索不一致（`candidate` 被误删）

Round 2 文档第 6.3 节已识别，且确实成立：

- `crud.py:55-65`：`_sync_to_vector` = `status != "active" → delete`，即 **`candidate` 会被删**。
- `memorycore/storage/curator_llm/core.py:355-364` `_fetch_active_memories` = `status IN ('active','candidate')`，curator 把 candidate 当活跃记忆去 embed/search。

任何一次对 candidate 记录的更新/status 变更都会把它从 Qdrant 删掉，使其从语义检索中**消失**，但 curator 仍把它当活跃候选反复处理。

### 🟠 P1-2：`_delete_app_memories` 绕过向量同步，制造 stale point

`memorycore/frontend_helpers.py:375-395`：`/api/v1/apps/{id}` DELETE 直接 `UPDATE memories SET status='archived'`，**不调 `_sync_record_indexes`**。整批归档一个 app 的记忆后，其向量残留 Qdrant，永远不会被删（因为 curator 的 rebuild 是 dry-run，不兜底清理）。

### 🟠 P1-3：异步 upsert 与同步 delete 的竞态 → 已归档向量复活

`crud.py:67-87`：upsert 走 `threading.Thread(..., daemon=True)` fire-and-forget；delete 是同步的（`:56-64`）。顺序「add → 立即 archive」时，add 派生的 upsert 线程可能在同步 delete 之后才落地，把**已归档记忆的向量重新写回 Qdrant**。

文档所称「stale point 累积」风险的真正来源是此竞态与 P1-2，而不是「缺增量同步」。

### 🟠 P1-4：明文 API key 可被无鉴权接口读取

- `config.yaml:19`（工作树）是真实 deepseek key `sk-c5cf...`。`git status` 显示 `M config.yaml`，key 尚未提交（HEAD 里是占位符 `nk`），但工作树随时可能被误提交，风险持续存在。
- `frontend_helpers.py:108-142` `_read_memorycore_config` 把 `api_key` 原样返回给 `GET /api/v1/config`。
- `serve` 默认不带 `--auth-token`（`server_runtime.py:200` 默认空），`server.py:87` 的 `/api/*` 路由无鉴权直接可达。
- `frontend_helpers.py:145-178` `_write_memorycore_config` 允许任意客户端改写 config。

### 🟠 P1-5：进程内 `_start_auto_curator` 每 6h 在主服务线程跑 rollup

`server_runtime.py:34-66` + `:379`：serve 进程内部启动 6h 循环线程，执行 `rollup_report(dry_run=False)`、`_drain_vector_sync_queue`、`auto_expire_stale_reviews`。`rollup_report` 走 `_call_rollup_llm`（deepseek LLM，`memorycore/storage/rollup.py:100-130`）+ `add_memory_record`（后者又触发 P0-1 的同步 supersession embed）。

这直接推翻前序文档 2.1 节「curator 是独立进程，不占用主服务线程」的说法——还有一个独立于 systemd 的、跑在 serve 进程内的批处理任务，同样会拖慢 API。

### 🟡 P2-1：`memory_rebuild_vectors` 只 upsert 不 delete，真正重建入口几乎不可达

`transfer.py:335-372`：只对非 archived 逐条 `vs.upsert`，**从不清理已归档/已删除记录的 stale point**。能触发 `dry_run=False` 的入口只有 `semantic-index --force`（`server_runtime.py:307`）与 full-replace import（`transfer.py:313`），日常无人跑。因此 Qdrant 的「清理」完全依赖 `_sync_to_vector` 的正确性——而 P1-2/P1-3 已证明它不完整。

### 🟡 P2-2：`run_llm_curator_incremental` status 判定可读性/正确性隐患

`report.py:393`：

```python
status = "failed" if errors and counts.get("decisions_created", 0) == 0 else "succeeded" if counts.get("decisions_created", 0) else "done"
```

有错误但产生了决策 → 仍报 `succeeded`；「有 errors 却 succeeded」会误导监控/前端。

### 🟡 P2-3：模块级单例 `get_vector_store` 非线程安全初始化

`vector_store.py:590-598`：`if _store is None: _store = VectorStore(...)` 无锁。多线程首调可能并发创建两个 client（泄漏连接、`atexit.register` 重复）。并发下概率低，但属初始化竞态。

---

## 4. 建议修复优先级

1. **P0-1**：把 `process_auto_supersession` 的向量相似度计算移出 `memory_add` 同步路径（复用 `_sync_to_vector` 的异步模式；或先做 lexical 快筛，只对少数候选做向量比对）。这是 120s 超时的直接根因。
2. **P0-2 / P0-3**：`embed_text` 降级为 hashing 时必须让调用方可感知（返回失败/标记 degraded），且 `search` 的「服务不可用」不得与「无匹配」混为一谈。
3. **P1-1**：统一 status 语义（Qdrant 保留 `active + candidate`，与 `_fetch_active_memories` 对齐）。
4. **P1-2 / P1-3**：`_delete_app_memories` 补向量删除；消除 upsert 异步与 delete 同步的竞态。
5. **P1-4**：key 移出 config 到 `.env`，给 `/api/v1/config` 加鉴权，serve 默认启用 token。
6. **P1-5**：评估 `_start_auto_curator` 的 rollup 是否应移出 serve 进程（并入 systemd curator，或降级为 dry-run）。

---

## 5. 关键路径清单（审查核对）

- 全量重建（dry-run 事实）：`memorycore/storage/transfer.py:335` `memory_rebuild_vectors(dry_run=True)`
- 调用点（未传参 → dry-run）：`memorycore/storage/curator_llm/report.py:388`、`:431`
- 增量同步（已存在）：`memorycore/storage/mutation_executor.py:166,457-465` `_sync_results`
- 批量 apply 增量同步：`memorycore/storage/governance_ops.py:427`
- 规则 curator 同步：`memorycore/storage/curator.py:361` → `crud.py:378-397` `update_status_batch`
- 同步 embed 洪流（P0-1）：`crud.py:284-287` → `temporal_governance.py:62,146-149`
- 静默降级（P0-2/P0-3）：`memorycore/vector_store.py:139-186,303-314,381-383,485-486`
- status 语义（P1-1）：`crud.py:55-65` vs `core.py:355-364`
- 绕过同步（P1-2）：`memorycore/frontend_helpers.py:375-395`
- 明文 key（P1-4）：`config.yaml:19`、`frontend_helpers.py:108-142`
- 进程内批处理（P1-5）：`server_runtime.py:34-66,379`
- 单例竞态（P2-3）：`vector_store.py:590-598`

---

## 6. 验证与回滚

- 本文档全部结论均来自对源码的逐行核对，行号在写作时无漂移；改动前建议以 `git diff` 复核。
- 前序文档中仍有效的部分（systemd `Nice/CPUWeight/IOWeight` 降级、timer 降频错峰）与本报告不冲突，可独立执行。
- 本报告未改动任何生产代码，仅新增文档；如需按第 4 节落地，逐项小改、可精确回滚。

---

## 7. 实施记录（2026-08-17，与本文档同日）

以下修复已落地并通过全量测试（508 passed / 7 skipped）：

| 项 | 改动 | 文件 |
|---|---|---|
| P0-1 | 自动 supersession 的向量搜索从「每候选一次」hoist 为「每次 add 一次」（50→1 次 embed） | `memorycore/storage/temporal_governance.py` |
| P0-2 | 全部 embed fallback 路径补齐 `embedding_degraded` 审计 + 计数器，`status()` 暴露 `embed_fallback_count` | `memorycore/vector_store.py` |
| P1-1 | `_sync_to_vector` / `_drain_vector_sync_queue` 统一为 `active/candidate→upsert，其余→delete` | `memorycore/storage/crud.py` |
| P1-2 | `_delete_app_memories` 归档后逐条同步删除向量 | `memorycore/frontend_helpers.py` |
| P1-3 | 异步 upsert 线程写入前重查当前 status（竞态窗口收窄到单次 upsert 调用） | `memorycore/storage/crud.py` |
| P1-4 | `/api/v1/config` 返回脱敏 key（`sk-****abcd`），GET→PUT 回写时忽略脱敏值；`LOCAL_MEMORY_LLM_API_KEY` 加入提取 key 解析链（与 `.env.example` 对齐） | `memorycore/frontend_helpers.py`、`memorycore/extraction.py` |
| P1-5 | 进程内 auto-curator 移除 `rollup_report(dry_run=False)`（保留廉价的 handoff/向量队列/过期评审维护）；rollup 移入 systemd `run_curator.sh`（`LOCAL_MEMORY_ROLLUP_*` 可控制） | `memorycore/server_runtime.py`、`run_curator.sh` |
| P2-1 | `memory_rebuild_vectors` 查询对齐 `active/candidate`，并在重建后按 payload status 过滤删除 stale point | `memorycore/storage/transfer.py` |
| P2-2 | `run_llm_curator_incremental` status 判定改写为可读分支（语义不变） | `memorycore/storage/curator_llm/report.py` |
| P2-3 | `get_vector_store` / `reset_vector_store` 加锁，消除单例初始化竞态 | `memorycore/vector_store.py` |

新增测试：`tests/test_auto_supersession.py`（单次 search hoist）、`tests/test_vector_sync.py`（candidate→upsert）、`tests/test_frontend.py`（app 归档同步删向量、config key 脱敏、脱敏值回写保护）、`tests/test_extraction.py`（env 链更新）。

### 7.1 仍需人工执行的部署步骤

1. **P1-4 收尾（密钥迁移）**：把 `config.yaml` 里的 `extraction.api_key` 移出到 `.env`（已 gitignore）：
   ```bash
   cd /home/advancer/project/memorycore
   echo "DEEPSEEK_API_KEY=sk-..." > .env
   ```
   然后清空 `config.yaml` 的 `extraction.api_key` 为 `''`，重启服务：
   ```bash
   systemctl --user daemon-reload
   systemctl --user restart mcore.service mcore-curator.service
   ```
   （`extraction_config_from_dict` 已支持 `DEEPSEEK_API_KEY` / `LOCAL_MEMORY_LLM_API_KEY` env 解析，systemd 两个服务都已加载 `.env`。）
2. **P1-5 收尾**：重启 `mcore.service` 使进程内移除 rollup 生效（`run_curator.sh` 无需重启，下次定时器自动生效）：
   ```bash
   systemctl --user restart mcore.service
   ```
3. **P0-2/P0-3 补充建议（未实施）**：`embed_text` 降级时调用方仍无显式感知（仅审计/计数）；`search` 的「服务不可用」与「无匹配」仍同返回 `[]`。彻底区分需改 `search` 返回契约，涉及多个调用方，建议单独立项。

### 7.2 已知残留

- **P1-3 竞态**：重查 status 将窗口收窄到单次 `vs.upsert` 调用，未完全串行化（彻底修复需按 memory id 的锁/队列）。
- **`_vector_search_ids`（memory_context 向量检索）不带 status 过滤**：依赖同步路径删除保证不返回 stale；P2-1 的重建清理可兜底，但检索路径的 status 过滤是否纳入 `candidate` 需另行决策。

