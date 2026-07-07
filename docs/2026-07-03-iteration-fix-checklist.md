# MemoryCore 迭代修复清单

> 基于 2026-07-03 深度审计报告，按依赖关系和风险排序。
> 每个步骤标注预估耗时、影响范围、验证方法。

---

## 第一轮：止血（运行时崩溃 + 白屏）

> 目标：修复所有会导致功能不可用的问题。不改架构，不删文件，只修 bug。

### 1.1 后端缺失 import 修复
- [ ] `api_helpers.py` 顶部添加 `import yaml`
- [ ] `api_routes.py` 顶部添加 `import uuid`
- **耗时**：5 分钟
- **影响**：配置保存和 LLM Curator 触发恢复正常
- **验证**：Settings 页面保存配置；前端触发 LLM Curator 运行

### 1.2 前端全局 Error Boundary
- [ ] 创建 `ui/app/error.tsx`（"use client" 组件，接收 error + reset）
- [ ] 为 Graph 页面创建 `ui/app/graph/error.tsx`（3D 渲染最易崩溃）
- **耗时**：10 分钟
- **影响**：渲染期异常不再白屏，用户可重试
- **验证**：故意在组件中 throw Error，确认错误页面显示

### 1.3 SSR 守卫
- [ ] `lib/api-url.ts` 的 `_migrateAndGet()` 函数开头添加 `if (typeof window === 'undefined') return DEFAULT_API_URL`
- **耗时**：5 分钟
- **影响**：SSR 环境不再崩溃
- **验证**：`pnpm build` 成功

**第一轮完成标志**：所有页面可正常打开，配置可保存，LLM Curator 可触发。

---

## 第二轮：类型安全（消除 `any`，修复 Hook）

> 目标：消除运行时类型错误风险。逐文件改，每改一个文件跑一次 `tsc --noEmit`。

### 2.1 统一错误捕获模式（20 处）
- [ ] 全局替换 `catch (err: any)` → `catch (err: unknown)`
- [ ] 每处添加类型守卫：`err instanceof Error ? err.message : 'Unknown error'`
- **涉及文件**：
  - `hooks/useAppsApi.ts`（4 处）
  - `hooks/useConfig.ts`（5 处）
  - `hooks/useFiltersApi.ts`（1 处）
  - `hooks/useMemoriesApi.ts`（10 处）
- **耗时**：30 分钟
- **验证**：`grep -rn "err: any" hooks/` 返回 0 结果

### 2.2 补全 Memory 接口
- [ ] `components/types.ts` 的 Memory 接口添加 `valid_from?: string`、`valid_until?: string`
- [ ] `store/appsSlice.ts` 的 `vector: any` → `vector: number[] | null`
- [ ] `store/profileSlice.ts` 的 `apps: any[]` → `apps: App[]`
- [ ] `hooks/useStats.ts` 的 `apps: any[]` → `apps: App[]`
- [ ] `components/types.ts` 的 `metadata: any` → `metadata: Record<string, unknown>`
- **耗时**：20 分钟
- **验证**：`grep -rn ": any\|as any" hooks/ store/ components/types.ts` 返回 0

### 2.3 Graph3D 类型处理（12 处）
- [ ] `app/graph/Graph3D.tsx` 中的 THREE.js 相关 `any` 用具体类型或 `unknown` + 断言替代
- [ ] `graphRef` 使用 `ForceGraph3DInstance` 类型（从 `3d-force-graph` 导入）
- **耗时**：30 分钟
- **验证**：`grep -rn ": any\|as any" app/graph/` 返回 0

### 2.4 修复 useEffect 依赖项（7 处）
- [ ] `components/dashboard/MemoryOperationsPanel.tsx:175` — fetchStatus 用 useCallback 包裹
- [ ] `components/dashboard/Stats.tsx:20` — fetchStats 同上
- [ ] `app/settings/page.tsx:45` — 添加 fetchConfig, toast, messages 依赖
- [ ] `app/memories/page.tsx:15` — 添加 searchParams, router 依赖
- [ ] `app/memories/components/FilterComponent.tsx:97` — 添加 handleClearFilters
- [ ] `app/governance/page.tsx:67` — 移除 eslint-disable，添加 setDecisionType
- [ ] `app/memory/[id]/page.tsx:21` — 添加 fetchMemoryById
- **耗时**：30 分钟
- **验证**：`pnpm build` 无 exhaustive-deps 警告

### 2.5 添加 AbortController 清理（5 处）
- [ ] `app/memories/components/MemoriesSection.tsx:34`
- [ ] `app/memory/[id]/components/RelatedMemories.tsx:24`
- [ ] `app/memory/[id]/components/AccessLog.tsx:29`
- [ ] `app/memory/[id]/components/MemoryLineage.tsx:110`
- [ ] `app/graph/useGraphPage.ts:80-85`
- **模板**：参考 `hooks/useGovernanceCockpit.ts:326-336` 的正确实现
- **耗时**：20 分钟
- **验证**：React StrictMode 无 warning

**第二轮完成标志**：`grep -rn ": any\|as any" hooks/ store/ components/ app/` 返回 < 5 处（仅保留确实无法避免的）；`pnpm build` 零 warning。

---

## 第三轮：瘦身（删除死代码和未使用组件）

> 目标：减少维护面积。每删一批跑一次构建确认不破坏。

### 3.1 删除未使用的 shadcn/ui 组件（10 个文件）
- [ ] 删除以下文件：
  - `components/ui/accordion.tsx`
  - `components/ui/resizable.tsx`
  - `components/ui/toggle.tsx`
  - `components/ui/drawer.tsx`
  - `components/ui/command.tsx`
  - `components/ui/collapsible.tsx`
  - `components/ui/pagination.tsx`
  - `components/ui/separator.tsx`
  - `components/ui/form.tsx`
  - `components/ui/use-mobile.tsx`（与 hooks/ 重复）
- **耗时**：10 分钟
- **验证**：`pnpm build` 成功

### 3.2 删除前端死代码
- [ ] 删除 `components/dashboard/Stats.tsx`（0 引用）
- [ ] 检查并移除 package.json 中对应的未使用 Radix UI 依赖：
  - `@radix-ui/react-accordion`
  - `@radix-ui/react-collapsible`
  - `@radix-ui/react-context-menu`
  - `@radix-ui/react-menubar`
  - `@radix-ui/react-navigation-menu`
  - `@radix-ui/react-toggle`
  - `@radix-ui/react-toggle-group`
  - （每个先 grep 确认 0 引用再删）
- **耗时**：15 分钟
- **验证**：`pnpm build` 成功 + `pnpm install` 无 peer dep 报错

### 3.3 清理后端死代码
- [ ] `memorycore/__init__.py:28` 删除 `SQLITE_VEC_AVAILABLE = False`
- [ ] `memorycore/server.py:115` 删除 `SQLITE_VEC_AVAILABLE = False`
- [ ] `server.py` 中 11 个未注册函数：
  - 决策：`memory_curator_report`、`memory_rollup_report`、`memory_atomize_report` → **注册为 @mcp.tool()**
  - 决策：8 个 `governance_*` 函数 → **删除**（api_routes.py 直接调用 storage 层，这些包装函数多余）
- [ ] 删除 `memorycore/storage/curator_llm.py.bak`（备份文件）
- **耗时**：20 分钟
- **验证**：`python -m pytest tests/ -q` 全部通过

### 3.4 添加 feedback_events 索引
- [ ] `memorycore/storage/db.py` 的 `init_db()` 中添加：
  ```python
  conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_memory ON feedback_events(memory_id)")
  ```
- **耗时**：5 分钟
- **验证**：`EXPLAIN QUERY PLAN SELECT * FROM feedback_events WHERE memory_id='test'` 显示使用索引

**第三轮完成标志**：前端删除 12 个文件 + 若干 Radix 依赖；后端删除 ~160 行死代码 + 注册 3 个 MCP 工具；索引补齐。

---

## 第四轮：样式统一（Graph 模块重点）

> 目标：消除所有硬编码颜色和内联样式，统一设计语言。

### 4.1 注册 Tailwind 自定义 token
- [ ] `tailwind.config.ts` 中 `theme.extend.colors` 添加：
  ```
  graph-bg: '#020408'
  glass-border: 'rgba(255,255,255,0.06)'
  glass-bg: 'rgba(3,5,10,0.94)'
  ```
- **耗时**：10 分钟

### 4.2 逐文件迁移 Graph 模块样式
- [ ] `GraphNodeDetail.tsx` — 12 处内联样式 → Tailwind class
- [ ] `GraphFilterPanel.tsx` — 10 处内联样式 → Tailwind class
- [ ] `GraphTopbar.tsx` — 8 处内联样式 → Tailwind class
- [ ] `GraphNodeList.tsx` — 4 处内联样式 → Tailwind class
- [ ] `app/graph/page.tsx` — 3 处内联样式 → Tailwind class
- **每个文件改完后验证**：Graph 页面视觉无回归
- **耗时**：2 小时
- **验证**：`grep -rn 'style={{' app/graph/` 返回 < 3 处（仅保留需要动态计算的 width/height）

### 4.3 统一硬编码颜色
- [ ] 将 `#64748B` → `text-slate-500`
- [ ] 将 `#FBBF24` → `text-amber-400`
- [ ] 将 `#06B6D4` → `text-cyan-500`
- [ ] 将 `#60A5FA` → `text-blue-400`
- [ ] 将 `#52525b` → `text-zinc-600`
- [ ] 将 `#3f3f46` → `text-zinc-700`
- **耗时**：30 分钟
- **验证**：`grep -rn '#[0-9a-fA-F]\{6\}' app/graph/ components/` 返回 < 5 处

**第四轮完成标志**：Graph 模块视觉不变，但所有颜色走 Tailwind token，支持未来主题切换。

---

## 第五轮：交互体验

> 目标：补全空状态、加载状态、错误反馈，提升易用性评分。

### 5.1 空状态设计（6 个页面）
- [ ] Dashboard — 无数据时显示欢迎引导卡
- [ ] Memories — 空列表时显示"创建第一条记忆"引导
- [ ] Graph — 无节点时显示"暂无记忆关系图"+ 引导
- [ ] Governance — 无决策时显示"所有决策已处理"+ CheckCircle 图标
- [ ] Apps — 无应用时显示"尚未接入任何 Agent"引导
- [ ] Settings — 连接失败时显示重试引导
- **耗时**：1.5 小时
- **验证**：清空数据后逐页检查

### 5.2 加载状态统一
- [ ] Dashboard 各面板统一使用 Skeleton 骨架屏（参考现有 MemoryIntelligenceSkeleton）
- [ ] Memories 表格加载时显示行骨架屏
- [ ] Graph 加载时显示粒子动画或进度条（替代纯文字"Computing layout..."）
- **耗时**：1 小时
- **验证**：模拟慢网络（Chrome DevTools Throttle），确认各页面有骨架屏

### 5.3 操作确认与反馈
- [ ] Curator 的 Apply / Run LLM 操作添加二次确认 AlertDialog
- [ ] Governance 的 Reject 操作添加确认对话框（与 Approve All 对齐）
- [ ] 所有 toast 消息检查：移除通用的"出错了"，替换为具体描述
- **耗时**：1 小时
- **验证**：点击每个危险操作按钮，确认弹出确认框

### 5.4 国际化清理
- [ ] Governance 页面硬编码中文（"条/页"、"已应用 ${n} 条"等）迁移到 i18n
- [ ] 检查其他页面的硬编码中文字符串
- **耗时**：30 分钟
- **验证**：切换语言后无未翻译文本

**第五轮完成标志**：所有页面空状态有引导，加载有骨架屏，危险操作有确认，无硬编码中文。

---

## 第六轮：后端架构优化

> 目标：拆分巨型文件，统一状态管理，修复 N+1。

### 6.1 拆分 governance.py（1253 行 → 4 个文件）
- [ ] 提取 `storage/governance_policy.py` — 策略网关 + 决策创建
- [ ] 提取 `storage/governance_decisions.py` — 查询 + 筛选 + 统计
- [ ] 提取 `storage/governance_actions.py` — 应用 + 拒绝 + 回滚 + 批量
- [ ] 保留 `storage/governance.py` 作为导入入口（从 3 个子模块 re-export）
- [ ] 更新 `storage/__init__.py` 导出
- **耗时**：2 小时
- **验证**：`python -m pytest tests/ -q` 全部通过

### 6.2 修复 N+1 查询
- [ ] `api_routes.py:456` 的循环逐条 `update_status` → 批量 UPDATE：
  ```python
  update_status_batch(ids, "archived")
  ```
- [ ] `api_routes.py:500` 同上
- **耗时**：30 分钟
- **验证**：归档 100 条记忆，观察日志中 SQL 执行次数 = 1（而非 100）

### 6.3 统一 LLM Curator 状态管理
- [ ] `frontend.py` 中 `_llm_curator_jobs` 内存字典 → 改为从 SQLite `llm_curator_jobs` 表读取
- [ ] 删除 `_llm_curator_lock` 和内存字典
- [ ] `_start_llm_curator_job()` 改为直接写 SQLite 表
- **耗时**：1 小时
- **验证**：触发 LLM Curator → 重启服务 → 查询状态仍可见

**第六轮完成标志**：governance.py < 100 行（只剩 re-export）；N+1 消除；LLM Curator 状态重启不丢失。

---

## 第七轮：工程规范

> 目标：建立代码质量门槛，防止回归。

### 7.1 后端 Linter + Formatter
- [ ] `pyproject.toml` 添加 ruff 配置：
  ```toml
  [tool.ruff]
  line-length = 120
  select = ["E", "F", "I", "N", "W", "UP"]
  
  [tool.ruff.format]
  quote-style = "double"
  ```
- [ ] 执行 `ruff check --fix .` 修复自动可修复问题
- [ ] 执行 `ruff format .` 统一格式
- **耗时**：30 分钟
- **验证**：`ruff check .` 零错误

### 7.2 前端构建检查
- [ ] `next.config.mjs` 改 `eslint: { ignoreDuringBuilds: false }`
- [ ] `next.config.mjs` 改 `typescript: { ignoreBuildErrors: false }`
- [ ] 修复暴露的类型/lint 错误（在第二轮完成的基础上应该很少）
- **耗时**：1 小时
- **验证**：`pnpm build` 成功且无 warning

### 7.3 CI 增强
- [ ] `.github/workflows/ci.yml` 添加：
  - `ruff check .`（后端 lint）
  - `cd ui && pnpm build`（前端构建检查）
  - `pytest --cov=memorycore --cov-fail-under=60`（覆盖率门槛）
- **耗时**：30 分钟
- **验证**：push 后 CI 全绿

### 7.4 补充缺失文件
- [ ] 创建根目录 `.env.example`（列出所有环境变量 + 注释）
- [ ] 创建 `CHANGELOG.md`（从 ITERATION.md 提取关键版本）
- **耗时**：20 分钟
- **验证**：文件存在且内容完整

**第七轮完成标志**：ruff + ESLint + 构建检查 + CI 覆盖率门槛全部到位。

---

## 第八轮：性能与 DX

> 目标：提升开发者体验和运行时性能。

### 8.1 后端热重载
- [ ] `start.sh` 开发模式添加 `--reload` 参数：
  ```bash
  uvicorn memorycore.server:app --reload --port 8318
  ```
  或在 `cli.py serve` 子命令中添加 `--dev` flag
- **耗时**：30 分钟
- **验证**：修改 Python 文件后服务自动重启

### 8.2 Seed 数据
- [ ] 创建 `scripts/seed.py`，生成 50 条示例记忆（覆盖各类型/状态/agent）
- [ ] `start.sh` 添加 `--seed` 参数
- **耗时**：30 分钟
- **验证**：`bash start.sh --seed` 后前端显示有意义的数据

### 8.3 前端性能
- [ ] `next.config.mjs` 改 `images: { unoptimized: false }`
- [ ] 添加 `experimental: { optimizePackageImports: ['lucide-react', 'recharts'] }`
- **耗时**：15 分钟
- **验证**：`pnpm build` 输出 bundle 大小比改前小

### 8.4 数据库维护
- [ ] `schema_version` 表添加实际版本检查逻辑（当前形同虚设）
- [ ] 考虑添加 WAL checkpoint 定时调用，控制 memory.sqlite3 大小（当前 571MB）
- **耗时**：1 小时
- **验证**：`PRAGMA wal_checkpoint(TRUNCATE)` 后文件大小减小

---

## 总览

| 轮次 | 目标 | 预估耗时 | 前置依赖 |
|------|------|----------|----------|
| **第一轮：止血** | 修复运行时崩溃 + 白屏 | 20 分钟 | 无 |
| **第二轮：类型安全** | 消除 any，修复 Hook | 2.5 小时 | 第一轮 |
| **第三轮：瘦身** | 删除死代码和未使用组件 | 50 分钟 | 第一轮 |
| **第四轮：样式统一** | Graph 模块样式迁移 | 2.5 小时 | 第三轮 |
| **第五轮：交互体验** | 空状态 + 加载 + 确认 | 4 小时 | 第二轮 |
| **第六轮：后端架构** | 拆文件 + 修 N+1 + 状态统一 | 3.5 小时 | 第三轮 |
| **第七轮：工程规范** | Linter + CI + 构建检查 | 2.5 小时 | 第二轮 + 第六轮 |
| **第八轮：性能与 DX** | 热重载 + Seed + 优化 | 2 小时 | 第七轮 |

**总预估**：~18 小时（约 3 个工作日）

**并行可能**：第二轮和第三轮可同时进行（前端类型安全 vs 删除文件互不冲突）；第四轮和第六轮可同时进行（前端样式 vs 后端架构）。

```
第一轮（止血）
  ├─→ 第二轮（类型安全）─→ 第五轮（交互体验）─┐
  │                                              ├─→ 第七轮（工程规范）─→ 第八轮（性能DX）
  └─→ 第三轮（瘦身）─→ 第四轮（样式统一）────┘
                     └─→ 第六轮（后端架构）──────┘
```
