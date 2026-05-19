window.memoryPlatformData = {
  projectTitle: "OpenMemory + Qdrant 多 Agent 共享记忆平台",
  thesis: "将 local-memory-mcp 升级为强大的适配器与治理层，利用 OpenMemory 和 Qdrant 提供企业级记忆能力。",
  stack: [
    { name: "OpenMemory/mem0", role: "主记忆与用户画像" },
    { name: "Qdrant", role: "向量检索与 Embedding 存储" },
    { name: "local MCP adapter", role: "治理、Context Pack 与 Agent 路由" },
    { name: "SQLite Ops DB", role: "反馈、审计与 Curator 元数据" },
    { name: "Graphiti/Zep", role: "未来时间演化与事件层" }
  ],
  architecture: {
    layers: [
      { name: "Agent 接入层", components: ["Hermes Agent", "Codex CLI", "Claude Code"], notes: "统一的 MCP 工具接入。" },
      { name: "Adapter / Router 层", components: ["local-memory-mcp"], notes: "Token 预算控制、Context Pack 生成与路由。" },
      { name: "存储层", components: ["OpenMemory", "Qdrant", "SQLite"], notes: "主记忆、向量搜索与运维元数据。" },
      { name: "时间演化层 (未来)", components: ["Graphiti / Zep"], notes: "事实演化与矛盾关系图。" }
    ]
  },
  responsibilitySplit: {
    outsource: [
      "向量数据库实现",
      "自动记忆抽取",
      "用户画像逻辑",
      "语义搜索基础设施"
    ],
    keep: [
      "任务相关的 Context Pack 压缩",
      "治理维度 (scope, project_path, importance)",
      "Curator 逻辑与反馈闭环",
      "多 Agent 路由与 Token 预算管理"
    ]
  },
  dataModel: {
    fields: [
      { name: "id", group: "身份", type: "string", desc: "唯一记录标识符" },
      { name: "backend", group: "身份", type: "enum", desc: "openmemory | sqlite | server-memory | graphiti" },
      { name: "type", group: "治理", type: "enum", desc: "user_profile | decision | project_memory 等" },
      { name: "scope", group: "治理", type: "enum", desc: "global | project | agent | user" },
      { name: "status", group: "治理", type: "enum", desc: "active | stale | archived | contradicted | candidate | promoted | expired" },
      { name: "importance", group: "治理", type: "float", desc: "记录的重要性权重" },
      { name: "valid_from", group: "时间", type: "ISO8601", desc: "事实有效期开始时间" },
      { name: "valid_until", group: "时间", type: "ISO8601", desc: "事实有效期结束时间" },
      { name: "supersedes", group: "时间", type: "string[]", desc: "被此记录取代的旧记录 ID" },
      { name: "source_agent", group: "溯源", type: "string", desc: "创建此记录的 Agent 名称" },
      { name: "feedback_score", group: "反馈", type: "float", desc: "用户反馈对记忆的影响得分" }
    ],
    types: [
      { name: "user_profile", desc: "用户偏好、身份、长期习惯。" },
      { name: "environment_fact", desc: "本地环境、工具安装、网络问题。" },
      { name: "project_memory", desc: "特定项目的稳定约定。" },
      { name: "decision", desc: "明确的架构或设计决策。" },
      { name: "timeline_event", desc: "发生过的重要事件。" },
      { name: "skill_candidate", desc: "可提升为 skill 的流程知识。" },
      { name: "raw_event", desc: "尚未整理的原始事件输入。" }
    ]
  },
  temporal: {
    lifecycle: [
      { type: "user_profile", policy: "review, 不自动过期" },
      { type: "environment_fact", policy: "refresh_after_30d" },
      { type: "project_memory", policy: "review_after_60d" },
      { type: "decision", policy: "never_expire unless superseded" },
      { type: "timeline_event", policy: "archive_after_180d" },
      { type: "raw_event", policy: "archive_after_14d" },
      { type: "skill_candidate", policy: "promote_or_archive_after_30d" }
    ],
    governance: [
      "Supersede: 新事实取代旧事实，同时保留历史。",
      "Contradiction: 冲突的事实触发 Curator 告警。",
      "Expiration: 环境与原始事实的基于时间的衰减。"
    ]
  },
  roadmap: [
    { phase: 0, title: "基线冻结与备份", status: "Ready", milestones: ["备份 memory.sqlite3", "导出当前 README 和 dashboard 状态", "记录当前工具列表与配置"] },
    { phase: 1, title: "Backend Abstraction", status: "Ready", milestones: ["定义 MemoryBackend 基类", "SQLite 抽象封装", "确保现有测试通过"] },
    { phase: 2, title: "OpenMemory 集成", status: "Planned", milestones: ["增加 OpenMemory client", "字段映射层实现", "支持写 OpenMemory + SQLite audit"] },
    { phase: 3, title: "Qdrant + 真实 Embedding", status: "Planned", milestones: ["配置 Qdrant collection", "接入 Ollama/sentence-transformers", "语义搜索替换 hashing fallback"] },
    { phase: 4, title: "Context Pack v2", status: "Planned", milestones: ["基于重要性与反馈的混合排序", "Token 预算压缩策略", "Stale 事实告警区"] },
    { phase: 5, title: "反馈与 Curator v2", status: "Planned", milestones: ["反馈写入 SQLite Ops DB", "矛盾候选检测", "Dashboard 展示 backend 状态"] },
    { phase: 6, title: "时间演化 / 矛盾处理", status: "Planned", milestones: ["增加 temporal 字段", "实现 memory_resolve_contradiction", "实现 memory_refresh_facts"] },
    { phase: 7, title: "Graphiti/Zep 评估接入", status: "Planned", milestones: ["评估成熟 temporal graph 产品", "PoC 验证", "决定是否正式引入"] }
  ],
  migration: {
    strategy: "双写阶段 (Double Write) -> 切读阶段 (Read Switch) -> 归档清理 (Cleanup)",
    order: [
      "environment_fact (环境事实)",
      "user_profile (用户画像)",
      "project_memory (项目记忆)",
      "decision (决策记录)",
      "timeline_event (时间线事件)",
      "skill_candidate (技能候选)",
      "raw_event (原始事件)"
    ]
  },
  risks: [
    { risk: "OpenMemory 数据模型不匹配", impact: "Medium", mitigation: "Adapter 统一模型 + SQLite Ops DB 保存治理字段" },
    { risk: "Qdrant/embedding 运维变重", impact: "Low", mitigation: "Docker/本地二选一，提供 fallback" },
    { risk: "多 Agent 写入冲突", impact: "High", mitigation: "source_agent、scope、feedback、curator 审计" },
    { risk: "自动矛盾处理误伤", impact: "Medium", mitigation: "不删除，只改状态；高风险进入 dry-run report" },
    { risk: "事实过期策略过激", impact: "Low", mitigation: "stale 进入 warning，不直接消失" },
    { risk: "WSL 网络问题", impact: "Medium", mitigation: "优先本地 embedding/Qdrant/OpenMemory" }
  ],
  tasks: [
    { id: 1, phase: 0, title: "创建项目配置文件", status: "todo", desc: "新增 adapter 配置，不影响旧逻辑。" },
    { id: 2, phase: 1, title: "拆出 MemoryRecord 模型", status: "todo", desc: "建立统一记录模型，避免 backend 泄漏。" },
    { id: 3, phase: 1, title: "增加 backend abstraction", status: "todo", desc: "将 SQLite 操作抽象为 backend 接口。" },
    { id: 4, phase: 2, title: "增加 OpenMemory client mock", status: "todo", desc: "先用 mock 固定接口，不依赖真实服务。" },
    { id: 5, phase: 2, title: "实接 OpenMemory", status: "todo", desc: "调通本地 OpenMemory endpoint。" },
    { id: 6, phase: 3, title: "增加 Qdrant backend status", status: "todo", desc: "先只检测 Qdrant，不切语义检索。" },
    { id: 7, phase: 3, title: "替换 semantic_search", status: "todo", desc: "用 Qdrant + real embedding 替换 hashing fallback。" },
    { id: 8, phase: 4, title: "Context Pack v2", status: "todo", desc: "统一多源检索结果，生成预算内上下文。" },
    { id: 9, phase: 5, title: "Temporal fields", status: "todo", desc: "增加时间演化字段，不改变旧调用。" },
    { id: 10, phase: 5, title: "Contradiction candidates", status: "todo", desc: "curator 能报告潜在矛盾。" },
    { id: 11, phase: 6, title: "Fact expiration", status: "todo", desc: "引入 decay policy 和 expired 状态。" },
    { id: 12, phase: 6, title: "Dashboard 更新", status: "todo", desc: "展示 backend、temporal、curator 状态。" }
  ],
  decisionSummary: {
    recommendation: "采用 thin-adapter 架构。将沉重的记忆管理外包给 OpenMemory 和 Qdrant，同时保留对治理、多 Agent 上下文和本地审计的控制。",
    note: "避免自研向量数据库；优先考虑工作流集成和时间演化管理。"
  },
  configSkeleton: `backend:
  primary: openmemory
  fallback: sqlite

openmemory:
  url: http://localhost:8765
  user_id: e-pengyang
  timeout: 30

qdrant:
  url: http://localhost:6333
  collection: agent_memory
  timeout: 30

embedding:
  provider: ollama
  model: nomic-embed-text
  dim: 768

context_pack:
  default_token_budget: 2000
  include_stale_warnings: true
  max_records_per_group: 6

temporal:
  enabled: true
  contradiction_detection: heuristic
  auto_supersede_user_corrections: true

ops_db:
  path: /home/advancer/.agent-memory/local-memory-mcp/memory_ops.sqlite3`
};
