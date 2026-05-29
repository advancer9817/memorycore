# TODO — local-memory-mcp

> 待办事项清单。完成后打 `[x]`，具体实现细节记入 ITERATION.md。

---

## 检索质量优化

- [x] 清理过时高权重记忆（Phase 8 任务清单、Overmind 借鉴特性等已完成项 → archived）
- [x] FTS5 查询从 OR 改为 AND（2 词以上用 AND 连接，减少宽泛匹配）
- [x] FTS5 排序加入 rank 权重（文本相关性 40% + importance 30% + effectiveness 20% + feedback 10%）
- [x] 向量搜索融合到 context pack（FTS5 + Qdrant 双路召回，合并去重，Qdrant 不可用时降级纯 FTS5）

## 功能

- [ ] Embedding sentence-transformers 降级（Ollama 不可用时自动切换）
- [ ] 修复 rollup 测试隔离问题：`test_rollup_processes_manual_source_episodic` 在本机全量测试中会因真实 extraction 配置触发外部 LLM 调用并超时；应让 dry-run/force 测试使用 stub summarizer 或隔离测试配置，避免依赖外部服务。

## 取舍决策 / 简化项

- [ ] 删除 agent/model 权限管理：移除 `agent_permission_*` MCP 工具、权限表/检查逻辑和相关前端/API 入口；lmmcp 作为个人本地记忆总线，不再维护半成品 RBAC。
- [ ] 修复前端 `/api/vector/search` 的 `score_threshold` 参数传递：当前第三个位置参数误传为 `filters`，应改为关键字参数并补前端 API 回归测试。
- [ ] 自动生成 MCP 工具文档：用脚本从 `server.py` 的 `@mcp.tool()` 函数签名/docstring 生成 `docs/tools.md`，并加测试确保文档与实际工具列表一致。
- [ ] 将 `semantic-*` CLI 改为真实 Qdrant 功能：`semantic-status` 调 `VectorStore.status()`，`semantic-search` 调 Qdrant search，`semantic-index` 调 `memory_rebuild_vectors()`，不再只返回 sqlite-vec 移除提示。
- [ ] 不新增 LLM 全自动记忆治理管线；继续强化现有规则型 `curator` / `rollup`，优先做可解释、可回滚的状态迭代、归档、重复检测、重要性调整和总结沉淀。
- [ ] `start.sh` 默认安装完整依赖 `.[all]`：一键启动应包含 Qdrant vector 与 extraction 能力，避免新设备只装 `.[extraction]` 导致语义检索降级。
- [ ] 明确 audit 导入策略：`memory_export(include_audit=True)` 可导出 `audit_events`，但 `memory_import()` 不导入本机审计日志，并在返回结果中报告 `ignored_tables=["audit_events"]`，避免静默丢弃。
- [ ] `start.sh` 增加 venv 路径漂移检测：若 `.venv/bin/pytest` / `.venv/bin/pip` shebang 指向旧 checkout 路径，则自动重建 `.venv`，避免 bad interpreter。
- [ ] 收敛 MCP 工具面但不引入 admin profile：直接删除/合并低价值工具，优先删除 `agent_permission_*`，将 `memory_update_status` 并入 `memory_update`，将 `memory_consolidate` 并入 `memory_curator_report`，避免新增角色/权限复杂度。

## 发布与部署

- [ ] PyPI 首次发布（打 tag 触发 publish workflow，验证安装可用）
- [ ] Docker Compose 完善（取消注释 Qdrant 服务，端到端验证）
- [ ] README 补充 PyPI 安装说明和 Docker 快速启动文档
