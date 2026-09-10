# MemoryCore (mcore) 阿里工程规约与技术细节实现方向规范

> **文档定位**：`docs/mcore-aliyun-coding-guidelines-and-implementation-details.md`  
> **镜像归档**：`/workspace/output/mcore-aliyun-coding-guidelines-and-implementation-details.md`  
> **制定日期**：2026-09-10  
> **核心基准**：全面对齐《阿里巴巴 Java 开发手册》（泰山版/嵩山版）与阿里云企业级研发规约，针对 MemoryCore 从 Python 单机系统向 **Java 17 (LTS) + Spring Boot 3.3.3 + Spring AI 1.0.0-M2 + PostgreSQL 16 (pgvector) + Vue 3.4 (Vite + TypeScript + Pinia)** 全栈重构制定权威技术实现方向与编码红线。

---

## 一、 领域模型与工程分层规约 (Layering & Models)

遵循阿里标准分层架构体系（Web ➔ Service ➔ Manager ➔ DAO），严禁业务逻辑越层穿透与模型跨层污染：

### 1. 分层职责与调用约束
* **Web 层（Controller / Filter）**：
  * 职责：负责 HTTP / MCP 请求接入、JSR-303/380 参数校验、租户上下文提取与 VO 数据封装；
  * 约束：严禁直接调用 DAO 层，严禁在 Web 层编写混合检索算法或直接操作数据库连接。
* **Service 层（业务服务层）**：
  * 职责：编排核心记忆生命周期业务（如记忆召回排序流、画像冲突过滤、版本比对、租户开辟业务流）；
  * 约束：面向接口编程，核心业务接口统一定义在 `mcore-common` / API 模块，实现类强制以 `Impl` 结尾。
* **Manager 层（通用业务能力层）**：
  * 职责：
    1. 动态多租户数据源调度与物理连接池生命周期管理（`TenantDataSourceManager`）；
    2. 封装第三方交互与外部网络协议，如 Spring AI MCP Server 协议转换与 Embedding 外部接口适配与降级；
    3. 统一二级缓存控制（Caffeine LRU 活跃租户池淘汰与监控）。
  * 约束：对底层持久化异常与第三方网络异常进行标准化转译，向上提供高可靠通用能力。
* **DAO 层（Repository）**：
  * 职责：专注于纯粹的持久化读写与 PostgreSQL 16 / pgvector 单 SQL 算子交互；
  * 约束：禁止在 DAO 层抛出业务受检异常，禁止在 DAO 层处理与业务逻辑相关的条件拼接。

### 2. 领域模型命名与流转红线
* **DO (Data Object)**：与租户数据库表结构严格一一映射，以 `DO` 结尾（如 `MemoryDO`、`LinkDO`），仅限 DAO 与 Manager 层内部流转，严禁直接暴露至 Web 控制层。
* **DTO (Data Transfer Object)**：跨层、跨模块及 MCP 协议交互数据传输对象，以 `DTO` 结尾（如 `MemorySearchDTO`、`ContextPackDTO`）。
* **VO (View Object)**：面向前端 Vue 3 仪表盘与客户端接口的展示模型，以 `VO` 结尾（如 `TenantMetricsVO`、`VectorClusterVO`），剔除底层敏感与内部调试元数据。
* **Query / Param**：多参数查询入参对象封装，以 `Query` 结尾，禁止使用无类型安全的 Map 或零散的多参数传递。
* **POJO 命名禁令**：布尔类型字段**严禁以 `is` 开头**（规避 Jackson/Lombok 序列化导致的 RPC/JSON 属性丢失缺陷）；强制使用包装类型（如 `Long`、`Integer`、`Double`），杜绝基本类型默认值掩盖空值状态。

---

## 二、 多租户物理硬隔离与极速开辟实现方向 (Database-per-Tenant)

### 1. 控制面与数据面彻底解耦
* **控制面系统库（`mcore_system`）**：集中管理 `sys_users`、`sys_tenant_databases`、`sys_tenant_api_keys` 与 `sys_tenant_quotas`，负责租户生命周期、鉴权与配额审计。
* **数据面私有库集群**：每注册一个新用户，拥有独立的专属私有库（如 `mcore_u_<uid>`），独享独立的 17 张核心业务表与独立 pgvector 向量空间，彻底杜绝混表混库带来的 HNSW 向量索引拓扑污染与跨租户隐私泄露。

### 2. 写时复制（COW）秒级建库机制
* **非事务专用连接**：PostgreSQL 的 `CREATE DATABASE` 属于非事务性 DDL，控制面开辟引擎必须采用原生连接并显式启用自动提交（`autocommit = true`），脱离常规业务事务管理器的管控。
* **模板库状态锁**：数据面模板库 `template_mcore` 预装扩展（`vector`, `pg_trgm`, `btree_gin`）、`nocase` 校对规则与完整 Schema；常态下配置为禁止直接业务连接，仅作为写时复制克隆源，将单租户开辟耗时严格控制在 **30~50 毫秒** 内。
* **命名安全与沙箱白名单**：租户库命名强制遵循正则白名单校验（`^[a-zA-Z0-9_-]{1,32}$`），严禁拼接未清洗字符，彻底杜绝 DDL 注入。

---

## 三、 动态数据源路由与全局连接熔断体系 (Routing & Connections)

### 1. 微型租户连接池规范
* 单租户物理库采用 HikariCP 极轻量连接池（`minIdle = 1, maxPoolSize = 3`），仅在租户首个请求到达时惰性构建，严禁系统启动时盲目全量预热。

### 2. 全局连接硬上限与 LRU 自动回收
* **双层配额守卫**：针对 PostgreSQL 整机 150 全局连接硬上限，通过原子计数器（`AtomicInteger`）严格控制常驻活跃租户连接池上限（最大 40 个，极端峰值占用 120 条连接，保留 30 条安全冗余给系统库与高优运维）。
* **Caffeine LRU 弹性淘汰**：活跃租户池受控于 Caffeine LRU 缓存，单租户连续空闲超过 15 分钟自动触发回收与连接池 `close()`，释放底层系统文件描述符与数据库后端进程。

### 3. 上下文安全与 ThreadLocal 防泄漏铁律
* Web 过滤器与 MCP 请求拦截器在解析 `X-Tenant-Id` 或 Bearer Token 后写入 `TenantContextHolder`；
* **必须在 `try-finally` 的 `finally` 代码块中强制执行 `TenantContextHolder.remove()`**，严禁依赖垃圾回收，彻底切断线程池复用导致的上下文串扰与内存泄漏风险。

---

## 四、 单 SQL 算子混合检索与 Slim 信封引擎 (Search & Context Packing)

### 1. 单阶段（Single-Pass）算子下推
* 摒弃传统的“向量库查一次、全文检索查一次、内存粗暴合并”的多路召回模式；
* 依托 PostgreSQL 16 原生能力，将 pgvector 余弦距离计算（`<=>`）与 pg_trgm 三元词相似度计算（`similarity`）在单条 SQL 内部联合加权打分，大幅减少数据库往返延迟与全表扫描开销。

### 2. 动态加权评分矩阵
* **综合评分公式**：
  * 向量语义相似度分：占比 65%；
  * 三元词法重叠分：占比 25%；
  * 记忆重要度加成：占比 10%；
* **双通道保底过滤**：在 SQL `WHERE` 条件中对余弦距离与文本相似度设置保底筛选门槛，避免弱相关脏数据进入排序集。

### 3. Slim 紧凑信封与预算熔断截断
* 严格遵循迭代 220 确立的 Slim 紧凑契约，剥离内部调试元数据，信封体积降至原始体积的 1.4%；
* 在上下文装配层引入混合语言 Token 估算机制，累加体积到达预算上限（如 1200 Token）时立即实施熔断截断，保障 LLM 窗口高信噪比。

---

## 五、 并发与线程安全守则 (Concurrency & Thread Safety)

### 1. 自定义有界线程池规范（严禁 `Executors`）
* 全租户批量迁移、LLM 异步治理扫描、向量离线对账等异步任务，**严禁使用 `Executors` 静态工厂**创建无界队列线程池。
* 统一通过 `ThreadPoolExecutor` 显式创建：
  * 核心/最大线程数依据 CPU/IO 密集型公式精准设定；
  * 必须配置有界阻塞队列（如 `ArrayBlockingQueue`）；
  * 自定义 `ThreadFactory` 显式命名线程（如 `mcore-curator-%d`），确保堆栈清晰可溯；
  * 显式指定拒绝策略，默认采用 `CallerRunsPolicy` 降级减压。

### 2. 并发容器与锁颗粒度
* 统计与计数强制采用 `AtomicInteger` 或 `LongAdder` 进行高并发无锁操作；
* 涉及状态缓存更新时，优先使用 `ConcurrentHashMap` 原语，禁止大面积滥用粗粒度 `synchronized`。

---

## 六、 异常处理、统一契约与审计守则 (Exceptions & Logging)

### 1. 标准五位错误码体系
* 遵循阿里标准错误码体系：
  * `00000`：调用成功；
  * `Axxxx`：客户端错误（`A0400` 租户未注册、`A0401` 认证失败、`A0429` 超出配额限制）；
  * `Bxxxx`：系统与资源错误（`B0001` 全局连接池熔断打满、`B0002` 检索超时）；
  * `Cxxxx`：第三方服务错误（`C0001` 外部 Embedding 接口故障）。

### 2. 统一响应体封装
* REST 接口统一返回 `Result<T>`：
  * `success` (Boolean): 成功标识；
  * `code` (String): 标准五位错误码；
  * `message` (String): 用户友好提示；
  * `data` (T): 业务载荷对象；
  * `traceId` (String): 全链路追踪 ID（基于 MDC 透传）。

### 3. 日志规范与敏感数据脱敏
* 统一使用 SLF4J 门面，严禁字符串拼接，强制采用参数化占位符（`log.info("...", arg)`）；
* 记录异常堆栈时，必须将 `Throwable` 作为最后一个参数传入，严禁吞掉异常或仅输出 `e.getMessage()`；
* **敏感凭据脱敏防线**：API Key、密码、JWT Token 在日志打印与异常输出时必须统一替换为 `[REDACTED]`。

---

## 七、 数据库与事务管理规约 (Database & Transactions)

### 1. 事务边界最小化
* 声明式事务 `@Transactional` 必须显式指定 `rollbackFor = Exception.class`，防范非运行时异常漏回滚；
* **严禁在事务块中执行远程调用**：禁止在带有 `@Transactional` 的方法中调用外部 Embedding API 或大模型接口，防止外部网络延迟拖长事务持有时间，导致数据库连接池被迅速挤占耗尽。

### 2. 表结构规范与字段准则
* 表名、字段名必须全部使用小写字母与下划线，严禁驼峰式命名；
* 必须包含统一主键 `id` 以及标准带时区审计字段 `created_at` 与 `updated_at`；
* 单表索引严格控制在 6 个以内，pgvector 的 HNSW 索引必须明确指定 `vector_cosine_ops` 算子并配置合理的内存构建参数。

---

## 八、 前后端解耦与独立打包部署架构 (Decoupled Front-End & Deployment)

### 1. 前后端物理边界解耦
* **后端定位**：Java 17 + Spring Boot 3 独立构建为纯净的 `mcore-server.jar`，完全不打入静态网页，专注于 8318 端口暴露 FastMCP（`/mcp`）与核心 RESTful API，由独立 Linux 服务常驻守护；
* **前端定位**：Vue 3.4 + Vite 5 一键构建纯静态 SPA 资产（`dist/`），由 Nginx 或独立轻量静态 Web 服务托管于 18318 端口；
* **运维收益**：彻底终结 Next.js 常驻 Node.js 进程的高内存占用与进程崩溃；动静分离，前端样式与图表调整无需重启后端 JVM，保障 Agent 长会话零抖动。

### 2. 多租户状态响应链路
* Pinia 全局状态机维护当前租户标识，Axios 拦截器统一在请求头挂载 `X-Tenant-Id`；
* 顶栏私有库切换器切换时，触发全局事件并驱动视图与图表局部刷新。

### 3. 轻量化向量拓扑图谱
* 选用 Apache ECharts 渲染二维向量聚类力导向/散点图，替代重型 3D Canvas 方案，实现跨设备平滑缩放、类别高亮与高性能渲染。
