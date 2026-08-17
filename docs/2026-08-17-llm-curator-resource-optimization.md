# mcore llm-curator 资源占用优化 — 交接文档

> 状态：调查已完成，待执行优化方案（P0 可立即落地）
> 创建：2026-08-17
> 项目：/home/advancer/project/memorycore

---

## 1. 任务目标

解决 `llm-curator` 定时批量任务运行期间，主服务 `mcore.service`（:8318）API 响应严重变慢的问题。

实测现象：
- MCP `memory_add` 调用 `TimeoutError: MCP call timed out after 120.0s`
- `/api/v1/stats` 曾达 43s（平时 ~0.01s）
- 主服务健康检查 `/health` 正常，但写/检索路径被拖慢

---

## 2. 诊断结论（已完成，可直接采信）

### 2.1 运行机制

- `mcore.service`（主服务）：`python -m memorycore serve --host 127.0.0.1 --port 8318`
- `mcore-curator.service`（Type=oneshot，由 `mcore-curator.timer` hourly 触发）执行 `run_curator.sh`：
  1. 规则 curator：`memorycore curator --limit 500 --apply`（无 LLM，纯规则归档）
  2. LLM curator：`memorycore llm-curator --limit 200 --sim-threshold 0.72 --apply`
- **curator 是独立进程，不占用主服务线程**，但与主服务**共享 4 个资源**：SQLite（memory.sqlite3）、Qdrant（:6333）、Ollama embed（:11434）、deepseek LLM。

### 2.2 资源争用根因

一次 llm-curator 运行的调用量：

| 环节 | 调用量 | 代码位置 |
|---|---|---|
| 候选向量扫描 | 200 条 × (embed + Qdrant search) | `memorycore/storage/curator_llm/core.py:386` `_find_candidate_pairs` |
| LLM 判定 | ≤400 对 ÷ batch_size 5 ≈ 80 次 deepseek 调用 | `_llm_judge_duplicates` / `_llm_judge_contradictions` |
| **全量向量重建** ⚠️ | **≤5000 条记忆逐条 embed（串行、无缓存）** | `memorycore/storage/transfer.py:335` `memory_rebuild_vectors` |

**罪魁祸首 = 全量向量重建**：curator 每轮结束都 `rebuild_vectors=True` 触发，对全部非 archived 记忆（上限 5000）**逐条**调 Ollama `/api/embed`。curator 只改状态/决策，文本内容根本没变，重建是纯浪费。

放大因素：
1. `embed_text()` 无任何缓存，同样文本每次重算（`memorycore/vector_store.py:139`）
2. Ollama embed 是单条 HTTP 调用，未用 `/api/embed` 的数组批量能力
3. 定时器 `OnCalendar=hourly` + 300s 随机延迟，随时与在线使用撞车
4. 实测一轮 curator 跑了 17+ 分钟，CPU 仅 3s（99% 时间在等 embed/LLM 排队）

### 2.3 SQLite / 连接配置（已确认，无需改）

`memorycore/storage/db.py` 已配置 `PRAGMA journal_mode=WAL` + `busy_timeout=30000` + 60s PASSIVE checkpoint daemon，SQLite 层不是主要瓶颈。

---

## 3. 优化方案

### P0 — 立即可做（改配置 + 一行代码，消除 ~95% 占用）

**P0-1 关掉全量向量重建**
- `memorycore/server_runtime.py:261`：`run_llm_curator(..., rebuild_vectors=True)` → 改 `False`，或给 `llm-curator` 子命令加 `--no-rebuild` 参数（推荐，保留手动重建能力），`run_curator.sh` 的 llm-curator 调用处传入。
- curator 决策引发的状态变更（archive/supersede），改用 Qdrant `UpdateOperation` 按 id 更新 payload（不重新 embed），只刷受影响记录。
- 效果：embed 洪流从 5000 次/轮 → 200 次/轮。

**P0-2 curator 进程降级调度**
`~/.config/systemd/user/mcore-curator.service` 的 `[Service]` 段追加：
```ini
Nice=10
CPUWeight=10
IOWeight=10
```

**P0-3 定时器降频错峰**
`~/.config/systemd/user/mcore-curator.timer`：
```ini
OnCalendar=*-*-* 03:30:00,15:30:00
RandomizedDelaySec=600
```
（规则 curator 保持 hourly 无妨；LLM curator 每天 2 次足够，review_cooldown=900s + reviewed_ids 12h 冷却已限制重复评审。）

### P1 — 结构性修复（核心代码，一劳永逸）

**P1-4 Embed 内容哈希缓存（长期收益最大）**
新增 `vector_cache(text_sha256 PRIMARY KEY, vector_json, updated_at)` 表；`embed_text()` 先查哈希命中即返回；`memory_rebuild_vectors` 变为"只对缓存缺失记录 embed"，天然增量。

**P1-5 批量 Embed**
Ollama `/api/embed` 支持 `{"input": [t1, t2, ...]}`；逐条循环改 32~64 条/批。5000 条 → 80~160 次请求。`vector_store.py:462` 的 `upsert_batch` 已存在，但其 embed 部分仍是逐条调。

**P1-6 在线写路径异步化**
`memory_add` 的 `_sync_record_indexes`（embed+Qdrant upsert）改后台线程：SQLite 落库后立即返回 id，向量索引异步补（秒级最终一致）。

**P1-7 serve 进程内 embed LRU 缓存**
`memory_context` 高频检索对相同 query 重复 embed，加进程内 LRU（如 512 条）。

### P2 — 纵深防御（可选）

| # | 措施 |
|---|---|
| 8 | `embed_text` 层令牌桶限速（如全局 10 req/s） |
| 9 | curator 时长上限：`TimeoutStartSec=1800` + 代码 deadline（15min 中断输出 partial） |
| 10 | 给 curator 单独 ollama 实例（硬隔离，重方案，一般不需要） |
| 11 | `/api/v1/metrics` 增加 embed 等待时间/队列长度；dashboard 复用 `/api/curator/llm/latest` 展示运行状态 |

---

## 4. 建议落地顺序

```
今天  P0-1 关 rebuild（一行）＋ P0-2/P0-3 systemd 配置   → 立竿见影
本周  P1-4 哈希缓存 ＋ P1-5 批量 embed                    → 根治
下周  P1-6 异步索引 ＋ P1-7 LRM                           → 在线路径零等待
按需  P2 纵深项
```

---

## 5. 关键路径清单

- 服务：`~/.config/systemd/user/mcore.service`、`mcore-curator.service`、`mcore-curator.timer`
- 脚本：`/home/advancer/project/memorycore/run_curator.sh`
- 调度入口：`memorycore/server_runtime.py`（`llm-curator` 子命令，`run_llm_curator(..., rebuild_vectors=True)` 在 :261 附近）
- 全量重建：`memorycore/storage/transfer.py:335` `memory_rebuild_vectors(limit=5000)`
- 向量/embed：`memorycore/vector_store.py`（`embed_text` :139、`_embed_ollama` :213、`upsert` :429、`upsert_batch` :453）
- 候选扫描：`memorycore/storage/curator_llm/core.py:386`
- 报告生成：`memorycore/storage/curator_llm/report.py`（`run_llm_curator` :404、`run_llm_curator_incremental` :250）
- 配置：`/home/advancer/project/memorycore/config.yaml`（`llm_curator:` 段 :55，batch_size=5）
- venv：`/home/advancer/project/memorycore/.venv/bin/python`

---

## 6. 验证方法

1. 改完 P0-1 后，手动跑一轮：`run_curator.sh`（或 `mcore` 脚本），观察 `reports/llm-curator-*.json` 的 summary 里不再有 rebuild 结果、耗时明显下降。
2. curator 运行期间并发测主服务：`curl -w "%{time_total}" http://127.0.0.1:8318/api/v1/stats` 应保持 <1s。
3. 观察 `journalctl --user -u mcore.service --since "5 min ago"` 里 `11434/api/embed` 请求不再密集刷屏。
4. MCP `memory_add` 在 curator 窗口内不再超时（或走 P1-6 异步后彻底免疫）。
