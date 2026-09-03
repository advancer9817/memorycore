# MemoryCore (mcore) UI 重构设计方案：方案 C 模块化磁贴控制台 (Modular Widget Grid)

## 1. 概述与背景

用户对 mcore 现有 UI 界面不满意，主要痛点包括：
- 首页面板过长，单列线性无限堆叠导致垂直滚动冗长；
- 信息架构缺乏聚合性与主次层级，运维操作与大盘监控未能有机协同；
- 界面视觉存在历史样式混乱及色彩残留（旧版紫色/暖色混杂）。

在对 A、B、C、D 四套不同架构与原型视图进行深度比较后，用户最终选定 **方案 C：模块化磁贴 Widget 仪表盘 (Modular Widget Grid)** 作为全局重构基准。

---

## 2. 核心架构与布局设计

### 2.1 整体信息架构
- **全局顶栏 (`components/Navbar.tsx`)**：
  - 左侧：品牌 Logo (`/logo.svg`) + `MemoryCore` 标识 + 双核状态晶圆点（展示 SQLite & Qdrant Live 状态）。
  - 中间：核心页面导航（`Dashboard`、`Memories`、`3D Graph`、`Governance`、`Settings`），带动态待办决策角标（如 `12`）。
  - 右侧：全局快速搜索 (`⌘ K`)、多语言切换 (`LanguageSwitcher`)、页面级 SPA 静默刷新、新建记忆对话框 (`CreateMemoryDialog`)。
- **仪表盘工具栏 (`DashboardToolbar`)**：
  - 位于 Dashboard 顶层，支持重置默认 12 栅格布局，提供磁贴状态提示与快速动作。
- **12 列响应式自适应磁贴网格 (`grid grid-cols-12 gap-4`)**：
  - **Widget 1 (col-span-12 md:col-span-4)**：`HealthRadarWidget` —— 综合健康指数（Quality 78）、合规安全度（Risk 100%）、可用池总量及复用覆盖率。
  - **Widget 2 (col-span-12 md:col-span-4)**：`OperationsWidget` —— 紧凑四宫格快捷调度中心（规则扫描、LLM 治理唤醒、清理冷数据、一键归档）。
  - **Widget 3 (col-span-12 md:col-span-4)**：`AgentMatrixWidget` —— 智能体来源矩阵与活跃占比（Hermes、Claude、Rollup、Codex）及核心分类结构。
  - **Widget 4 (col-span-12 md:col-span-7)**：`GovernanceStreamWidget` —— 治理裁决建议流，集成最新待审决策（ARCHIVE、SUPERSEDE、MERGE），支持就地批准/忽略。
  - **Widget 5 (col-span-12 md:col-span-5)**：`ContextLabProbeWidget` —— 实时召回实验探针，支持直接输入 query 探测向量与词法打分，支持全屏/详情展开。

---

## 3. 视觉与设计规范 (Dark Mica / Graphite)

- **主色调与材质**：
  - 背景底色：`bg-zinc-950` (`#09090b`)，彻底清除历史紫色残留。
  - 磁贴容器：`bg-zinc-900/70 border border-zinc-800/80 backdrop-blur-md shadow-xl rounded-xl`。
  - 重点色彩系统：
    - 主操作与强调：深紫与科技蓝渐变 (`violet-600` / `blue-600`)。
    - 状态健康/正常：`emerald-500` (`#10b981`)。
    - 待审批/警告：`amber-500` (`#f59e0b`)。
    - 冲突/危险：`rose-500` (`#f43f5e`)。
- **交互规范**：
  - 每个 Widget 具有一致的头部标题栏、右上角控制区（参数设置/聚焦扩展）。
  - 保证全响应式：在手机/平板小屏幕自适应单列流式折叠，大屏（1024px+）完整展开为 12 列紧凑仪表盘。

---

## 4. 数据与后端接口交互

重构完全复用 mcore 现有的高效 REST API 端点：
1. `GET /api/v1/health-score`：获取综合质量分、安全风险分、活跃池与待治理积压。
2. `GET /api/v1/curator/status`：获取 Curator 定时任务、调度日志与统计数据。
3. `POST /api/v1/curator/run`：触发规则扫描或 LLM 治理任务。
4. `GET /api/v1/governance/counts` 与 `/api/v1/governance/decisions`：获取待治理提案与统计。
5. `POST /api/v1/governance/decisions/:id/apply` & `reject`：就地批准或忽略治理提案。
6. `POST /api/v1/context`：驱动 Context Lab 探针进行实时权重与相关度评估。

---

## 5. 国际化与工程规范红线

1. **i18n 字典完整性**：
   - `lib/i18n/dictionaries/en.ts` 与 `zh.ts` 必须严格保持 1:1 键对齐。
   - 所有函数 key 与字符串 key 保持严格一致，通过 `as const satisfies Messages` 类型检查。
2. **构建与运行验证**：
   - TypeScript 类型零错误（`pnpm build` 或 `tsc --noEmit` 通过）。
   - 服务端口：后端运行在 8318，前端 Next.js 运行在 18318，重启 systemd 服务确保生效。
