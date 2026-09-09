# MemoryCore (mcore) Java Spring Boot 3 + Spring AI 多租户全栈重构架构详案

> **归档位置**：`/workspace/output/mcore-spring-ai-multi-tenant-architecture.md`  
> **战略定调**：将 mcore 核心中枢从 Python 架构全面重构为 **Java 17 (LTS) + Spring Boot 3.3.x + Spring AI 1.0.0-M2 + PostgreSQL 16 (pgvector)** 企业级工程架构。  
> 选定长期支持版本 **JDK 17** 为运行基线，配合 Spring Boot 3.3 与 Spring AI 官方版本矩阵，实现数据面物理库隔离、毫秒级向量召回与全自动化生命周期管理。

---

## 一、 核心技术版本兼容矩阵 (Compatibility Matrix for JDK 17)

| 组件 | 选用版本 | 兼容性说明 |
|---|---|---|
| **JDK** | **17 (LTS)** | 工业级长期支持版，具备 Records 强类型模型、Text Blocks 复杂 SQL 模板、Sealed Classes |
| **Spring Boot** | **3.3.3** | 基于 Spring Framework 6.1，官方默认要求最低基线为 **Java 17**，原生内置 `JdbcClient` |
| **Spring AI** | **1.0.0-M2** | 官方适配 Spring Boot 3.3.x，原生内置 `spring-ai-mcp-server` 与 `PgVectorStore` |
| **HikariCP** | **5.1.0** | Spring Boot 3.3 内置，针对 Java 17 字节码优化的高性能数据库连接池 |
| **Caffeine** | **3.1.8** | 专为 Java 11+ 设计的高命中率 LRU 缓存，用于动态租户连接池治理 |
| **PostgreSQL / pgvector** | **16 / 0.1.6 (Java)** | 原生向量扩展与 JDBC 强类型映射适配器 |

---

## 二、 整体工程结构与模块划分 (Maven Multi-Module)

```
mcore-spring/
├── pom.xml                                   # 父工程统一依赖管理 (Java 17, Spring Boot 3.3.3, Spring AI 1.0.0-M2)
├── mcore-common/                             # 通用 DTO、实体模型、异常体系与常量定义
│   └── src/main/java/org/mcore/common/
│       ├── model/                            # MemoryRecord, LinkRelation, TenantContext
│       └── dto/                              # ContextPackResponse, SearchRequest, McpViews
├── mcore-tenancy/                            # 多租户动态数据源与物理库开辟引擎 (核心底座)
│   └── src/main/java/org/mcore/tenancy/
│       ├── routing/                          # TenantRoutingDataSource, TenantContextHolder
│       ├── pool/                             # TenantDataSourceManager (Caffeine LRU + Hikari)
│       └── provisioner/                      # TenantDatabaseProvisioner (PostgreSQL Template 克隆)
├── mcore-storage/                            # PostgreSQL 16 + pgvector 存储与混合检索
│   └── src/main/java/org/mcore/storage/
│       ├── repository/                       # MemoryRepository, LinkRepository (JdbcClient)
│       ├── search/                           # HybridSearchService (pg_trgm + pgvector <=> 联合排序)
│       └── pack/                             # ContextPackBuilder (Token 预算裁剪与护栏组装)
├── mcore-mcp/                                # Spring AI MCP Server 协议端点 (8318 端口)
│   └── src/main/java/org/mcore/mcp/
│       ├── tools/                            # MemoryMcpTools (@Tool 暴露 22 个标准工具)
│       └── interceptor/                      # McpTenantHeaderInterceptor (X-Tenant-Id 拦截)
└── mcore-server/                             # Web 入口、REST API 控制器与后台治理调度
    └── src/main/java/org/mcore/server/
        ├── controller/                       # MemoryController, CuratorController, StatsController
        ├── security/                         # TenantAuthFilter (Bearer Token / API Key 解析)
        └── curator/                          # ScheduledCuratorJob (多租户轮询治理引擎)
```

---

## 二、 动态多租户路由数据源 (`DynamicTenantRoutingDataSource`)

```java
package org.mcore.tenancy.pool;

import com.github.benmanes.caffeine.cache.Caffeine;
import com.github.benmanes.caffeine.cache.LoadingCache;
import com.github.benmanes.caffeine.cache.RemovalCause;
import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import org.mcore.tenancy.routing.TenantContextHolder;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.datasource.lookup.AbstractRoutingDataSource;

import javax.sql.DataSource;
import java.time.Duration;

public class DynamicTenantRoutingDataSource extends AbstractRoutingDataSource {
    private static final Logger log = LoggerFactory.getLogger(DynamicTenantRoutingDataSource.class);

    private final String host;
    private final int port;
    private final String username;
    private final String password;

    // LRU 缓存：最多保留 25 个活跃租户池，闲置超过 15 分钟自动关闭连接
    private final LoadingCache<String, DataSource> tenantPoolCache;

    public DynamicTenantRoutingDataSource(String host, int port, String username, String password, DataSource defaultDataSource) {
        this.host = host;
        this.port = port;
        this.username = username;
        this.password = password;
        setDefaultTargetDataSource(defaultDataSource);

        this.tenantPoolCache = Caffeine.newBuilder()
                .maximumSize(25)
                .expireAfterAccess(Duration.ofMinutes(15))
                .removalListener((String tenantId, DataSource ds, RemovalCause cause) -> {
                    if (ds instanceof HikariDataSource hikariDs) {
                        log.info("Evicting tenant pool [{}] due to {}, closing connections...", tenantId, cause);
                        hikariDs.close();
                    }
                })
                .build(this::createTenantDataSource);
    }

    @Override
    protected Object determineCurrentLookupKey() {
        return TenantContextHolder.getTenantId();
    }

    @Override
    protected DataSource determineTargetDataSource() {
        String tenantId = (String) determineCurrentLookupKey();
        if ("default".equalsIgnoreCase(tenantId)) {
            return (DataSource) getResolvedDefaultDataSource();
        }
        return tenantPoolCache.get(tenantId);
    }

    private DataSource createTenantDataSource(String tenantId) {
        String cleanId = tenantId.replace("-", "_").toLowerCase();
        String dbName = "mcore_u_" + cleanId;
        String jdbcUrl = String.format("jdbc:postgresql://%s:%d/%s?sslmode=prefer", host, port, dbName);

        HikariConfig config = new HikariConfig();
        config.setJdbcUrl(jdbcUrl);
        config.setUsername(username);
        config.setPassword(password);
        config.setPoolName("HikariPool-Tenant-" + cleanId);
        config.setMinimumIdle(1);
        config.setMaximumPoolSize(3);
        config.setIdleTimeout(300000);
        config.setConnectionTimeout(10000);

        return new HikariDataSource(config);
    }
}
```
