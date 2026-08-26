# E1 · 前端页面收敛与重设计（8 路由 → 5 导航核心页）执行方案

> 状态：**方案草案（未实施）**
> 日期：2026-08-26
> 关联：`docs/plans/2026-08-24-governance-slimming.md`（I11 衔接）、`docs/plans/2026-06-29-framework-redesign.md`（Phase 3/4）、skill `references/frontend-architecture-map.md`、`references/frontend-redesign-patterns.md`
> 前提：本轮迭代 22-24 已交付 config 热加载、维护闭环、画像闭环；服务健康（562 passed）

---

## 1. 背景与目标

### 1.1 现状
- 前端 56 组件 / ~1.7 万行 TS/TSX / **9 个路由页**：
  `/`(Dashboard+ContextLab)、`/memories`、`/apps`+`/apps/[appId]`、`/graph`、`/governance`、`/memory/[id]`、`/profile`、`/settings`
- 导航 7 项：Dashboard / Memories / Apps / Graph / Governance / Profile / Settings
- 架构地图已知痛点：
  - `MemoryOperationsPanel.tsx` 1029 行单体，与 `MemoryIntelligenceCenter` 各自独立拉 `curator/status`（重复请求）
  - 双 API 面：前端仍混用 7 处 legacy 调用（`/api/graph`、`/api/curator/*`、`/api/governance/*`）+ v1 调用（memories/apps/config/profile/maintenance 已 v1）
  - 前端硬编码健康度评分算法（`MemoryIntelligenceCenter`），口径与后端修复不同步
  - Apps / Governance 数据在导航中高频次要，页面整体心智负担重
- 用户既定偏好（来自决策/反馈记忆）：
  - 「极度反感手动审批」→ 治理默认自动执行，界面以**状态证明**为主（status panel 而非 operations panel）
  - 保留治理页结构诉求 → 治理页需重设计为「自动执行仪表」而非删除功能
  - Profile 独立 Tab（55aca57 已交付）→ 保留
  - 深色云母/石墨运维控制台风格（zinc-950 底 / zinc-900 卡片 / violet 点缀 / PageShell 骨架）
  - 自然流式滚动、`container mx-auto` 居中、禁止水平滚动、`h-[calc(100vh-64px)]` 匹配 root ScrollArea
  - i18n 双语同步（en.ts source of truth / zh.ts `as const satisfies Messages`）
  - 保留本地 UI 定制；不硬编码路径

### 1.2 目标
把「8 路由 + 7 导航」收敛为 **5 导航核心页 + 2 深层路由**，同时：
1. **降低每日操作心智负担**：Open 每日只看 Dashboard；治理/维护/应用都在一屏内可运营
2. **迁移遗留 API**：前端 100% 走 `/api/v1/*`（legacy 标注 deprecated，不在前端使用）
3. **消除重复/死代码**：dashboard 数据单请求、删除未引用组件、拆掉 1029 行单体
4. **评分与口径统一**：健康度评分迁移后端（`/api/v1/health-score`），前端只渲染
5. **统一设计系统**：global CSS token + 组件级规范落地

---

## 2. 目标信息架构（5 + 2）

| 层级 | 路由 | 内容 | 来源 |
|---|---|---|---|
| **核心页 1** | `/` Dashboard | 健康度/指标 + Context Lab + 治理状态（内联）+ 应用区块（内联）+ 一键维护（M1-M3 已有） | 原 `/` + `/governance`（整理为面板）+ `/apps`（内联）|
| **核心页 2** | `/memories` | 过滤 + 表格 + 分页 + 批量动作 | 原 `/memories`（保留）|
| **核心页 3** | `/graph` | 3D 知识图谱 + 节点/边面板 | 原 `/graph`（保留）|
| **核心页 4** | `/profile` | 用户画像仪表 + 覆盖度/置信度/来源 + 刷新动作 | 原 `/profile`（保留，用户既定）|
| **核心页 5** | `/settings` | Tab 化：通用 / LLM / Embedding / 策略 / 数据(导入导出/维护) / 高级 | 原 `/settings`（Tab 化升级）|
| **深层路由 A** | `/memory/[id]` | 记忆详情 + 血缘 + 相关 | 原详情（保留，不入导航）|
| **深层路由 B** | `/apps/[appId]` | 单应用详情（收藏入口保留） | 原详情（保留，不入导航）|

**路由变化汇总**
- 删除导航项：`/apps`（导航）→ 内联 Dashboard「应用」区块；`/governance`（导航）→ 内联 Dashboard「治理」面板
- 保留导航：`/`、`/memories`、`/graph`、`/profile`、`/settings`（5 项）
- 深层路由 `/apps/[appId]`、`/memory/[id]` 保留但不在导航展示
- `/governance`、`/apps` 旧路径：改为 301 重定向至 `/#governance`、`/#apps`（或保留空壳提示），**不立即删除**，观测一个迭代

---

## 3. 统一设计系统

### 3.1 设计 token（ThemeProvider 增强）
沿用现有 zinc 色系并抽成 CSS 变量（P2 逐步替换硬编码 class）：

| Token | 值 | 用途 |
|---|---|---|
| `--background` | zinc-950 | 页面底色 |
| `--card` | zinc-900 | 卡片 |
| `--card-hover` | zinc-800/80 | 悬停 |
| `--border` | zinc-800 | 边框/分隔 |
| `--foreground` | white/zinc-100 | 主文字 |
| `--muted` / `--muted-foreground` | zinc-500/400 | 次级文字 |
| `--accent` | violet-500（点缀）/ violet-400 文字 | 品牌/重点 |
| `--success` / `--warning` / `--danger` | emerald / amber / red | 状态语义 |

### 3.2 组件规范
- **PageShell**（统一骨架）：`<PageHeader title actions>` + `<main className="container mx-auto ..."><ScrollArea 高度匹配/自然流></main>`；所有页一致
- 卡片族：`Card`（标题+计数+悬浮）统一封装；Badge/Button/Table/EmptyState 全站复用
- **肯定式空状态**（green check + 文案）用于所有「队列为空」场景
- **折叠高级操作**（`dashboard.advancedOps` 模式）用于调参/危险区
- 禁止：水平滚动、全屏拉伸、`target="_blank"` 跳 `/memory/[id]`（沿用决策），新开页面一律页面内导航

### 3.3 数据流规范
- 所有页只调 `/api/v1/*`；legacy 路由由前端层适配器一次性映射（见 Phase 1）
- Dashboard 数据单请求：`GET /api/v1/dashboard`（后端聚合 stats+curator+governance counts+apps 摘要），前端 Redux 单 store 消费
- 时间/数字格式化统一 helper；请求错误统一 toast/内联提示

---

## 4. 逐页重设计

### 4.1 Dashboard（核心页 1）—— 最大工作量
1. **数据层**：新增 `GET /api/v1/dashboard`（聚合 stats / curator status / governance counts / apps 摘要 / maintenance latest）→ 前端一个请求；删除 `MemoryOperationsPanel` 与 `MemoryIntelligenceCenter` 各自拉 `curator/status` 的重复
2. **布局（从上到下自然流）**：
   - `PageHeader`：标题 + 刷新 + 新建记忆入口
   - 健康度横幅（读后端 `health-score`，不再前端算分）
   - 指标卡行（总数/活跃/候选/归档 + 画像属性总数）
   - **治理面板（内联）**：自动执行状态 + 最近决策列表（低风险已自动执行，仅极重要变更需人工）+ 一键维护（M1/M3 已有，原样保留）
   - **应用区块（内联）**：应用卡网格（来源/记忆数/最近活动），点击进 `/apps/[appId]`
   - Context Lab（现有组件正式化为「实验」抽屉/卡片，保留 `POST /api/v1/context/test` 链路）
3. **组件拆分**（拆掉 1029 行单体）：
   - `StatsCards`（指标卡行）
   - `CuratorActions`（运行/计划按钮区）
   - `LlmCuratorActions`（LLM 治理按钮 + 进度）
   - `LlmFindingList` + `LlmFinding`（LLM 结果列表）
   - `GovernancePanel`（新增：内联治理状态）
   - `AppsPanel`（新增：内联应用区块）
   - `MaintenancePanel`（现 `MemoryOperationsView` 的维护段抽成独立面板）

### 4.2 Memories（核心页 2）—— 低工作量
- 保留现有 Filters + Table + Pagination + 批量动作；统一走 v1（已走）
- 表格列可选定制（持久化到 localStorage）；新增批量归档/合并/清理入口复用 M1-M3 API
- 详情跳转保持 `/memory/[id]` 页面内导航

### 4.3 Graph（核心页 3）—— 低工作量
- 保留；`/api/graph` legacy → 迁 v1（`/api/v1/graph`），前端换调用
- 默认隐藏 supports/part_of 噪声边（沿用既有 pattern）

### 4.4 Profile（核心页 4）—— 低工作量
- 保留现有覆盖度/置信度/来源卡片；新增「增量刷新」（`extract?only_new=true`）按钮 + 过时告警展示（F3 已后端支持）

### 4.5 Settings（核心页 5）—— 中工作量
- Tab 化：**通用 / LLM / Embedding / 策略 / 数据 / 高级**
  - 通用：语言、输出风格
  - LLM：extraction/curator 的 base_url/model/key（key 掩码显示，`/api/v1/config` PUT）
  - Embedding：provider/model/ollama/api 配置
  - 策略：rule curator / llm curator / governance / extraction_strategy 参数表单（原 CuratorTuningPanel 迁移至此，Dashboard 只留预设下拉）
  - 数据：导入 / 导出 / 备份 / 维护记录（M1-M3 job 历史）
  - 高级：config reset、危险操作（折叠）
- JsonEditor 保留为「高级」内部高级编辑

---

## 5. 数据与 API 改造（前置依赖）

| # | 项 | 后端 | 说明 |
|---|---|---|---|
| A | `/api/v1/dashboard` 聚合 | 新增 | stats+curator+governance+apps+maintenance 一次返回；供 Dashboard 单请求 |
| B | `/api/v1/health-score` | 新增 | 健康度评分迁移后端（当前前端硬编码算法 → 后端实现，口径与 A/B 组修复对齐）|
| C | curator legacy → v1 | 迁移 | `/api/v1/curator/status\|apply\|llm/latest\|llm`（legacy `/api/curator/*` 标注 deprecated）|
| D | governance legacy → v1 | 迁移 | `/api/v1/governance/counts\|metrics\|decisions\|{id}/apply\|reject` |
| E | graph legacy → v1 | 迁移 | `/api/v1/graph` |
| F | `/api/v1/activity`（可选） | 新增 | 真实审计时间线（替换 Dashboard 硬编码 3 条 Timeline）|
| G | legacy 路由标注 | 后端 | 保留但响应头/日志标注 deprecated；下个迭代删除 |

**原则**：所有迁移均为「后端 v1 补齐 + 前端换址」，**前端不新增 legacy 依赖**；每个迁移独立 commit 可回滚。

---

## 6. 死代码 / 清理清单

| 项 | 证据 | 动作 |
|---|---|---|
| `IterationMetricsPanel.tsx` | 0 引用（I10.4 已知）| 删除 |
| `form-view-backup.tsx` | 疑似备份残留（核对引用）| 删除或合并 |
| `components/dashboard/intelligence/*` 未引用件 | 逐个 grep | 清理 |
| Agent 整条线前端残留 | I10 已删前端调用；复查 `agents\|handoffs` grep | 清残余 |
| 未使用 i18n keys | 相似 label 对比 | P3 清理 |
| `/apps`、`/governance` 独立路由（迁移后）| 导航移除 | 保留空壳重定向一个迭代后删除 |
| `dashboard.html` 导出 | 1.8MB 过时 | 标注废弃 |

---

## 7. 分阶段实施路线（每 Phase 独立可提交）

### Phase 1 — 基建（API 收敛 + 数据去重）约 1-1.5 天
- [ ] 后端：C/D/E/F（curator/governance/graph → v1；可选 activity）
- [ ] 后端：A/B（`/api/v1/dashboard`、`/api/v1/health-score`）
- [ ] 前端：legacy 调用全部换 v1；Dashboard 数据单请求（Redux 合并 curator/status）
- 验收：`grep -rn "/api/curator\|/api/governance\|/api/graph" ui/app ui/components`（除 Navbar 徽章）为空；Dashboard 网络面板 curator/status 仅 1 次请求；562+ 测试通过

### Phase 2 — 组件拆分 + 死代码（约 1 天）
- [ ] 拆 `MemoryOperationsPanel`（StatsCards/CuratorActions/LlmCuratorActions/LlmFindingList/LlmFinding）
- [ ] 删 `IterationMetricsPanel` 等死组件；`form-view-backup.tsx` 核对清理
- 验收：`MemoryOperationsPanel.tsx` 拆分后 ≤300 行/文件；无未引用组件（build 无警告）；页面行为与拆分前一致

### Phase 3 — 页面重设计（约 2-3 天）
- [ ] Dashboard：PageShell + 健康度横幅 + 治理面板内联 + 应用区块内联 + Context Lab 正式化
- [ ] Settings：Tab 化 + CuratorTuningPanel 迁移 + 数据页（导入导出/维护记录）
- [ ] Navbar：5 项导航 + `/apps` `/governance` 空壳重定向
- [ ] Profile：增量刷新按钮 + 过时告警
- 验收：9 路由 → `pages` 输出为 5+2；Dashboard 首次加载 API ≤3 请求；治理/应用功能在 Dashboard 可完整操作；i18n 无缺 key

### Phase 4 — 统一设计打磨（约 1-1.5 天）
- [ ] CSS token 落地（bg-background/border-border 等替换硬编码 zinc）
- [ ] 空状态/折叠/按钮组件规范统一巡检
- [ ] i18n 清理；`dashboard.html` 标注废弃
- 验收：全页面截图巡检（无水平滚动、无拉伸、风格一致）；`pnpm build` + 部署 + ui HTTP 200；全量回归

**总工作量粗估：5-7 天（可穿插在其他迭代间隙）**

---

## 8. 风险与回滚

| 风险 | 缓解 |
|---|---|
| API 迁移破坏现有页面 | 每项迁移独立 commit；v1 补齐后先改前端验证再标 legacy deprecated；phase 1 与 phase 3 之间页面双跑 |
| Dashboard 聚合过重 | `/api/v1/dashboard` 内部并行拉取；SSR 不依赖；失败逐项降级（返回部分字段 + 前端兜底）|
| 治理内联后可用性下降 | 治理面板默认展开「自动执行状态」+ 折叠决策列表；navbar 徽章保留（指向 /#governance）；不满意可回滚为独立路由（保留 /governance 代码一个迭代）|
| 路由删除引发书签/引用失效 | `/apps` `/governance` 保留 301 重定向空壳至少一个迭代 |
| 前端 hardcode 评分与后端不一致 | 评分全文迁移后端（health-score），前端删硬编码算法；后端单测覆盖 |
| i18n 缺失崩溃 | 遵循 en/zh 同步规则；`pnpm tsc` 前置检查 |

---

## 9. 验收口径（全局）

- [ ] 导航 5 项（Dashboard/Memories/Graph/Profile/Settings），9 路由收敛为 5+2；
- [ ] 前端 0 legacy API 调用（除明确标注 deprecated 兼容层）；
- [ ] Dashboard 首次加载 ≤3 次 API 请求；curator/status 不再重复；
- [ ] 健康度评分来自后端 `/api/v1/health-score`，口径与 B 组修复一致；
- [ ] 治理/维护/应用在 Dashboard 内可完整运营，空状态为肯定式；
- [ ] 全站 i18n 双语文案同步、无 `t.xxx is not a function`；
- [ ] `pnpm build` + 部署通过，无死组件/未引用文件告警；
- [ ] 全量后端测试 ≥ 目前基线（562 passed / 7 skipped），前端 tsc 零错误。

---

## 10. 决策记录（用户已拍板 2026-08-26）

| 问题 | 决策 |
|---|---|
| Governance 去向 | **A. 内联 Dashboard 面板** |
| Apps 去向 | **A. 内联 Dashboard「应用」区块** |
| 健康度评分迁移后端 | **A. 纳入（Phase 1 做 `/api/v1/health-score`）** |
| Context Lab 形态 | **A. 正式化为 Dashboard 卡片** |

> 采用推荐组合 1A+2A+3A+4A，按第 7 节分阶段实施。