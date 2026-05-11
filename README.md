# local-memory-mcp v0

本目录是本地/自托管多 agent 共享记忆层的 v0 实现。

## 目标

- 用 SQLite + FTS5 保存结构化长期记忆，而不是把所有内容塞进 USER.md / MEMORY.md。
- 给 Hermes、Claude Code、Codex 暴露同一个 MCP server。
- 提供关键工具：`memory_add`、`memory_search`、`memory_context`、`memory_timeline`、`memory_feedback`、`memory_consolidate`、`memory_curator_report`、`memory_semantic_*`。
- 保留官方 `@modelcontextprotocol/server-memory` 作为兼容层与迁移来源。

## 路径

- Server: `/home/advancer/.agent-memory/local-memory-mcp/local_memory_mcp.py`
- Python runtime: `/home/advancer/.agent-memory/local-memory-mcp/.venv/bin/python`
- SQLite DB: `/home/advancer/.agent-memory/local-memory-mcp/memory.sqlite3`
- Dashboard: `/home/advancer/.agent-memory/local-memory-mcp/dashboard.html`
- Protocol probe: `/home/advancer/.agent-memory/local-memory-mcp/probe_mcp.py`

## CLI

```bash
/home/advancer/.agent-memory/local-memory-mcp/.venv/bin/python \
  /home/advancer/.agent-memory/local-memory-mcp/local_memory_mcp.py init

/home/advancer/.agent-memory/local-memory-mcp/.venv/bin/python \
  /home/advancer/.agent-memory/local-memory-mcp/local_memory_mcp.py search memory

/home/advancer/.agent-memory/local-memory-mcp/.venv/bin/python \
  /home/advancer/.agent-memory/local-memory-mcp/local_memory_mcp.py context "继续实现多 agent 记忆架构"

/home/advancer/.agent-memory/local-memory-mcp/.venv/bin/python \
  /home/advancer/.agent-memory/local-memory-mcp/local_memory_mcp.py html

/home/advancer/.agent-memory/local-memory-mcp/.venv/bin/python \
  /home/advancer/.agent-memory/local-memory-mcp/local_memory_mcp.py curator --summary-only

/home/advancer/.agent-memory/local-memory-mcp/.venv/bin/python \
  /home/advancer/.agent-memory/local-memory-mcp/local_memory_mcp.py semantic-index --force

/home/advancer/.agent-memory/local-memory-mcp/.venv/bin/python \
  /home/advancer/.agent-memory/local-memory-mcp/local_memory_mcp.py semantic-search "delegate_task memory_context"

/home/advancer/.agent-memory/local-memory-mcp/run_curator.sh
```

## 本地测试与 CI

安装依赖：

```bash
cd local-memory-mcp
python -m pip install -r requirements.txt
```

如果使用 uv，也可以运行：

```bash
uv pip install -r requirements.txt
```

运行测试：

```bash
.venv/bin/python -m pytest tests/ -q
```

测试会通过 `LOCAL_MEMORY_DB` 指向 pytest 的临时 SQLite 文件，并在每个测试前清空初始化缓存，避免读写生产 `memory.sqlite3`。GitHub Actions CI 使用 Python 3.11，安装 `requirements.txt` 后执行同一组 pytest；CI 中 `LOCAL_MEMORY_DB=/tmp/ci_test_memory.sqlite3`。

## MCP configs

Hermes `~/.hermes/config.yaml`、Codex `~/.codex/config.toml`、Claude Code `~/.claude.json` 已增加 `local_memory` server。

验证：

```bash
hermes mcp test local_memory
codex mcp get local_memory
claude mcp get local_memory
```

## 设计边界

v0 解决“统一结构化存储 + MCP 工具 + context pack”问题；它还不是完整自进化系统。

已完成：

1. Hermes `delegate_task` 已增加可选的 `delegation.memory_context` 前置检索：对子 agent 构造 prompt 时调用 `local_memory.memory_context`，把小型 context pack 注入子 agent 的 ephemeral system prompt；主 agent 的基础 MEMORY.md / USER.md 与 prompt caching 面不变。
2. `curator` CLI/MCP 报告已支持重复标题、低反馈、stale、archive、矛盾候选、`skill_candidate` 推广候选；`run_curator.sh` 会输出 JSON 报告并刷新 dashboard。
3. `dashboard.html` 已增强为本地交互式面板：记录搜索/类型/状态/排序过滤、决策时间线、反馈健康分布、curator 候选摘要、semantic index 状态。
4. 已落地最小 sqlite-vec 向量层：安装 `sqlite-vec` + `numpy`，新增 `semantic-index/status/search` CLI 与 `memory_semantic_*` MCP 工具。当前 provider 是本地 `hashing-384` fallback，用于验证 vector plumbing 和轻量 fuzzy recall；它不是深度语义 embedding，后续可替换为 Ollama/sentence-transformers。

当前 Hermes 配置片段：

```yaml
delegation:
  memory_context:
    enabled: true
    server: local_memory
    tool: memory_context
    scope: global
    token_budget: 1200
```

下一阶段应该做：

1. 增加 curator cron：去重、合并、归档、矛盾检测、skill_candidate 推广。
2. 增加 HTML dashboard 过滤、时间线视图、反馈健康报告。
3. 评估 sqlite-vec/Qdrant/Ollama embeddings；等关键词/tag/context pack 稳定后再上语义层。
4. 把官方 server-memory 的实体/关系逐步迁移进 SQLite schema，并保留必要关系边。
