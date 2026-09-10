# MemoryCore (mcore) Java 17 + Spring Boot 3 + Spring AI + Vue 3 独立库多租户全栈重构工程规划方案

> **文档定位**：`docs/plans/2026-09-10-mcore-spring-boot-vue3-multi-tenant-architecture-plan.md`  
> **核心目标**：将 MemoryCore 从 Python 原型单机系统，全面升级为企业级、高吞吐、物理级多租户（Database-per-Tenant）的现代化全栈 AI Agent 记忆平台。  
> **技术矩阵**：**Java 17 (LTS) + Spring Boot 3.3.3 + Spring AI 1.0.0-M2 + PostgreSQL 16 (pgvector) + Vue 3.4 (Vite 5 + TypeScript + Pinia)**。

---

## 一、 架构演进决策与核心价值

1. **多租户物理硬隔离（Database-per-Tenant）**：
   - 每注册一个新用户，通过 PostgreSQL 原生 `template_mcore` 模板库在 30~50 毫秒内物理克隆专属独立库（如 `mcore_u_1001`）；
   - 彻底避免在共享表上混存向量导致 HNSW 索引拓扑污染与严重隐私穿透隐患；单租户备份注销极度轻巧（`pg_dump` / `DROP DATABASE`）。
2. **后端中枢企业级重构 (Java 17 + Spring Boot 3 + Spring AI)**：
   - 采用长期支持版本 **Java 17 (LTS)** 与官方基线 **Spring Boot 3.3.3**，天然规避 Python 运行时的 GIL 争用与协程死锁；
   - 官方 **`spring-ai-mcp-server-spring-boot-starter`** 原生实现标准 Model Context Protocol 工具暴露（8318 端口），无缝兼容 Claude Code、Hermes 与 Codex；
   - 利用 **`AbstractRoutingDataSource` + `HikariCP` + `Caffeine` LRU 缓存** 实现微型租户连接池（`min=1, max=3`，最多常驻 25 活跃池），空闲 15 分钟自动关闭连接，严格守护全局 150 连接上限。
3. **前端现代化与轻量化 (Vue 3 + Vite + TypeScript)**：
   - 彻底废除 Next.js 15 (React 19) 的独立 Node.js 常驻进程（18318 端口）与构建 standalone 资产缺失报错；
   - 确立**前后端严格分离、独立打包、独立部署**架构：
     - **后端**：输出纯净的 Spring Boot 可执行 JAR 包，专注于 FastMCP 服务（8318 端口 `/mcp`）与核心 REST API，不夹带任何前端静态文件；
     - **前端**：Vite 一键构建生成纯静态 SPA 产物（`dist/`），由高性能 Web 服务器（Nginx / Caddy / 轻量静态 Web 服务）独立承载（监听 18318 端口）；
     - **运维效益**：动静分离，前端界面与图表迭代无需重启后端 Java 虚拟机，后端升级不影响静态页面稳定访问。

---

## 二、 详细设计文档索引（位于 `docs/` 根目录）

本次全栈重构的完整设计拆解为三大专业领域专项文档，均已固化至 `docs/`：

1. 📂 **`docs/mcore-database-per-tenant-detailed-design.md`**：
   - **PostgreSQL 独立库多租户详细设计规范**：
     - 控制面系统库 `mcore_system` 表结构 DDL（`sys_users`, `sys_tenant_databases`, `sys_tenant_api_keys`, `sys_tenant_quotas`）；
     - 模板库 `template_mcore` 毫秒级物理克隆机制；
     - 动态连接池 LRU 调度与空闲探针回收算法；
     - 全租户批量版本升级运维脚本 `scripts/migrate_all_tenants.py`。
2. 📂 **`docs/mcore-spring-ai-multi-tenant-architecture.md`**：
   - **Java 17 + Spring Boot 3 + Spring AI 后端多租户全栈架构详案**：
     - Maven 多模块工程骨架划分（`mcore-common`, `mcore-tenancy`, `mcore-storage`, `mcore-mcp`, `mcore-server`）；
     - `pom.xml` 核心依赖与版本对齐矩阵（Java 17 LTS / Spring Boot 3.3.3 / Spring AI 1.0.0-M2）；
     - `DynamicTenantRoutingDataSource` 动态路由数据源与 `TenantContextHolder` 上下文无感透传；
     - 基于 `JdbcClient` 的单 SQL 混合检索（余弦距离 `<=>` + 全文三元词相似度联合打分）；
     - Spring AI `@Tool` 注解标准 MCP 服务实现。
3. 📂 **`docs/mcore-vue3-frontend-architecture.md`**：
   - **Vue 3 + Vite + TypeScript 前端现代化重构详案**：
     - 前端工程目录体系、Tailwind 主题与原子组件封装；
     - Axios 拦截器全自动注入 `X-Tenant-Id` 与 Bearer Token；
     - Pinia 租户状态机与顶栏极质感「私有记忆库快速切换器」组件；
     - Apache ECharts 驱动的高性能 2D 向量拓扑图谱组件；
     - 独立打包、动静分离与多环境部署指南 (Nginx 反向代理 + CORS 跨域解耦)。
4. 📂 **`docs/mcore-aliyun-coding-guidelines-and-implementation-details.md`**：
   - **阿里工程规约与技术细节实现方向规范**：
     - 四层分层架构（Web ➔ Service ➔ Manager ➔ DAO）与领域模型流转红线（DO/DTO/VO/Query）；
     - 自定义有界线程池与 ThreadLocal `try-finally remove()` 防泄漏守则；
     - 最小化事务边界与 `@Transactional(rollbackFor = Exception.class)`；
     - 五位标准错误码与统一 `Result<T>` 响应契约及日志脱敏规范。

---

## 三、 分步实施路线图与阶段规划 (Roadmap)

### Phase 1: 物理底座固化与模板库注册 (完成度: 100%)
- [x] 完成 PostgreSQL 16 + pgvector 原生系统服务割接（[迭代 237] 已闭环并通过 626 个单测）；
- [x] 注入 `nocase` Collation、`json_extract`、`datetime`、`group_concat` 与 `memories_fts` 兼容 Polyfill；
- [x] 注册基准只读模板库 `template_mcore`。

### Phase 2: 后端 Java 17 + Spring Boot 3 + Spring AI 脚手架与核心驱动 (进行中)
- [ ] 搭建 `mcore-spring` Maven 多模块工程与 Java 17 / Spring Boot 3.3.3 基础依赖；
- [ ] 落地 `TenantContextHolder` 与 `DynamicTenantRoutingDataSource` 动态路由；
- [ ] 对接现存 `mcore` 生产库，通过 `JdbcClient` 跑通单 SQL 混合检索与上下文召回；
- [ ] 挂载 `spring-ai-mcp-server`，实现 22 个 MCP 标准工具端点并绑定 8318 端口。

### Phase 3: 前端 Vue 3 + Vite 现代化重构
- [ ] 初始化 `mcore-ui-vue` 工程（Vue 3.4 + Vite 5 + Tailwind + Pinia）；
- [ ] 对齐现存 Next.js 的看板、记忆管理、图谱与自治理页面；
- [ ] 挂载顶栏私有库切换器与 ECharts 知识图谱；
- [ ] 验证前端独立构建纯静态产物（`pnpm build` -> `dist/`），Nginx / 静态服务独立托管并与后端 8318 接口联通。

### Phase 4: 多租户全链路联调与正式割接
- [ ] 控制面租户注册 API 接入，实测新用户注册 50ms 自动开辟 `mcore_u_<uid>` 私有库；
- [ ] Agent 客户端（Claude Code / Hermes / Codex）携带各自租户 Key 独立写入与召回；
- [ ] 正式下线 Python 运行时与 Node.js 运行时，完成企业级全栈交付。
