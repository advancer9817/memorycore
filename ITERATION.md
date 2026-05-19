# local-memory-mcp 迭代日志

## [迭代 7] 2026-05-18 — 模块重构 + MCP 循环导入彻底修复

**提交**: `Phase 7`（`git log --oneline --grep="Phase 7"` 可查具体 hash）

### 变更
- `local_memory_mcp/` 包结构: 将 1284 行的单文件拆分为 `models.py`/`storage.py`/`server.py`/`__init__.py`/`__main__.py`
- `local_memory_mcp/models.py`: 抽取常量、YAML 配置解析、类型验证、工具函数（无 MCP 依赖）
- `local_memory_mcp/storage.py`: 抽取 SQLite CRUD、FTS 搜索、curator、memory_links、dashboard 生成
- `local_memory_mcp/server.py`: FastMCP 实例、15 个 @mcp.tool() 注册、CLI main() 入口
- `local_memory_mcp/__main__.py`: 新增 `python -m local_memory_mcp` 入口
- `scripts/init_local_memory.sh`: 更新命令为 `python -m local_memory_mcp`
- `run_curator.sh`: 更新 SERVER 路径
- `probe_mcp.py`: 更新 MCP server 路径

### 修复
- `dedup.py`: 消除 `__main__` fallback 循环导入 → 改为直接从 `local_memory_mcp.storage` 导入（storage.py 无 MCP 依赖，彻底断绝循环链）
- **MCP 通道 `memory_ingest`**：此前即使显式传入函数引用，写入阶段仍因模块状态不一致失败。重构后 MCP 全链路验证通过（initialize → tools/list → memory_add → memory_ingest，全部正常返回）

### 验证
- 测试: **105/105 pass** (0 skipped)
- MCP 协议初始化: 正常握手，返回 `serverInfo: {"name": "local-memory-mcp", "version": "1.27.1"}`
- MCP tools/list: 返回 15 个工具（含 memory_ingest、memory_vector_search 等）
- MCP memory_add: 正常写入并返回记录
- CLI: `python -m local_memory_mcp init` 正常
- 导入验证: `from local_memory_mcp.storage import add_memory_record` + `from dedup import ingest` 无循环导入

### 已知问题
- （无新增已知问题；Phase 6 的 MCP 循环导入已修复）

### 下一步
1. curator cron job（定期去重/归档/矛盾检测）
2. 实体/关系迁移（从官方 server-memory，按需）
3. 多 Agent 集成增强

---

## 日志格式规范

每次提交必须在本文件顶部追加一条迭代记录，格式如下：

```markdown
## [迭代 N] YYYY-MM-DD — 标题

**提交**: `Phase N`（可通过 `git log --oneline --grep="Phase N"` 定位）

### 变更 (新增功能/接口/配置)
- `<文件路径>`: 变更描述

### 修复 (Bug 修复)
- `<文件路径>`: 问题描述 → 修复方式

### 验证
- 测试: N/N pass (skipped: N)
- 端到端: 关键链路验证结果

### 已知问题
- 问题描述（若有）

### 下一步
1. 下个迭代计划任务
```

> **规则**: 
> - 每次提交必须追加新条目（追加到文件顶部，即最新迭代在最上面）。
> - 变更与修复分开列出；如果某次提交仅有修复无新功能，"变更" 段可省略。
> - 测试结果必须写实际数字（如 105/105 pass），不允许占位符。
> - 已知问题如已在上个迭代修复，从列表中移除并改记入"修复"段。

---

## [迭代 6] 2026-05-15 — 端到端验证 + Qdrant server 模式 + 5 个 bug 修复

**提交**: `Phase 6`（`git log --oneline --grep="Phase 6"` 可查具体 hash）

### 变更
- `local_memory_mcp.py`: 新增 `update_memory_content()` — 按字段更新记忆（content/title/status/confidence/importance）
- `vector_store.py`: Qdrant 新增 server URL 模式，优先 Docker Qdrant，fallback 本地文件
- `vector_store.py`: `VectorStoreConfig` 新增 `url` 字段
- `config.yaml`: 移除 openmemory 残留；修正 `llm_base_url` 补全 `/v1`；`llm_api_key` 直接写入
- `local_memory_mcp.py`: `memory_ingest` 显式传递 `_add_memory_fn` / `_update_memory_fn` 避免循环导入
- `ITERATION.md`: 新建迭代日志文件及格式规范

### 修复
- `local_memory_mcp.py`: `update_memory_content` 缺失 → 新增完整函数（含 content/title/status/confidence/importance 字段更新）
- `extraction.py`: `os.environ.setdefault()` 被 Hermes 安全空值拦截 → 改为直接赋值 `os.environ[k]=v`
- `dedup.py`: `add_memory_record(type=...)` 参数名错误 → 修正为 `memory_type`（2 处）
- `dedup.py`: 增加 `__main__` fallback 导入（兼容 MCP server 循环导入场景）
- `config.yaml`: DeepSeek `base_url` 缺 `/v1` 导致 401 → 补全

### 验证
- 测试: **105/105 pass** (0 skipped)
- CLI 端到端: DeepSeek 提取(3-4s/次) → Qdrant 去重 → SQLite 写入 → Qdrant 语义索引 — 全链路通过
- Qdrant Docker 模式: 连接成功，向量读写正常（4 条记录）
- Curator: 扫描 16 条记录，报告正常，无异常候选
- MCP 通道 `memory_ingest`: 提取成功，写入阶段仍有 `__main__` 循环导入问题（4 errors / 4 facts）

### 已知问题
- MCP `__main__` 循环导入：`dedup.ingest` 即使显式传入函数引用，仍因模块状态不一致导致写入失败。CLI 通道完整通过，MCP 通道待重构后验证。

### 下一步
1. 重构模块结构，消除 `__main__` 循环导入
2. 跑通 MCP 通道完整 ingestion
3. 实体/关系迁移（从官方 server-memory）
4. 增加 curator cron job（定期去重/归档/矛盾检测）
