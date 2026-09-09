# MemoryCore (mcore) 独立数据库多租户架构详细设计规范 (Database-per-Tenant Detailed Design)

> **归档位置**：`/workspace/output/mcore-database-per-tenant-detailed-design.md`  
> **文档版本**：v1.0.0 (生产实施基准)  
> **设计目标**：实现基于 PostgreSQL 16 + pgvector 的物理库级多租户（Database-per-Tenant）Agent 记忆中枢，支撑多用户并发注册、物理级数据与向量空间隔离、毫秒级库克隆、动态连接池弹性回收与统一版本迁移。

---

## 一、 系统架构全景拓扑 (System Topology)

整个系统由**控制面（Control Plane）**与**数据面（Data Plane）**构成清晰的双层解耦架构：

```
                    ┌────────────────────────────────────────────────────────┐
                    │           Agent 客户端 / Web UI / 外部应用             │
                    │   (Claude Code / Hermes / Codex / Vue 3 Dashboard)     │
                    └───────────────────────────┬────────────────────────────┘
                                                │ HTTP / FastMCP (Bearer JWT / X-Tenant-Id)
                                                ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 mcore 服务端运行时                                     │
│                                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │                              租户鉴权与上下文拦截中间件                           │  │
│  │   • Token 解析 (JWT claims -> tenant_id)                                         │  │
│  │   • ContextVar / ThreadLocal 注入: TenantContextHolder.set(tenant_id)             │  │
│  └────────────────────────────────────────┬─────────────────────────────────────────┘  │
│                                           │                                            │
│               ┌───────────────────────────┴───────────────────────────┐                │
│               ▼                                                       ▼                │
│  ┌─────────────────────────┐                             ┌─────────────────────────┐  │
│  │   控制面路由 (Control)  │                             │    数据面路由 (Data)    │  │
│  │  • 用户注册 / 登录认证   │                             │  • memory_search/context │  │
│  │  • 租户配额 / 库生命周期 │                             │  • CRUD / 图谱 / 向量召回│  │
│  └────────────┬────────────┘                             └────────────┬────────────┘  │
│               │                                                       │                │
│               ▼                                                       ▼                │
│  ┌─────────────────────────┐                             ┌─────────────────────────┐  │
│  │  系统元数据连接池       │                             │  动态租户连接池管理器   │  │
│  │  (System ConnectionPool)│                             │ (TenantPoolRegistry-LRU)│  │
│  └────────────┬────────────┘                             └────────────┬────────────┘  │
└───────────────┼───────────────────────────────────────────────────────┼────────────────┘
                │                                                       │
                ▼                                                       ▼
┌───────────────────────────────┐               ┌────────────────────────────────────────┐
│     【控制面系统库】          │               │         【数据面租户私有库集群】       │
│        mcore_system           │               │                                        │
│  • sys_users                  │  克隆基准库   │  ┌─────────────────┐ ┌───────────────┐ │
│  • sys_tenant_databases       │ ────────────> │  │  mcore_u_1001   │ │ mcore_u_1002  │ │
│  • sys_tenant_api_keys        │ template_mcore│  │ (User A 私有库) │ │(User B 私有库)│ │
│  • sys_tenant_quotas          │               │  │ • 独立 pgvector │ │• 独立 pgvector│ │
│                               │               │  │ • 独立 17 张表  │ │• 独立 17 张表 │ │
│                               │               │  └─────────────────┘ └───────────────┘ │
└───────────────────────────────┘               └────────────────────────────────────────┘
```

---

## 二、 控制面：系统元数据库设计 (`mcore_system`)

```sql
CREATE DATABASE mcore_system OWNER mcore_user;
\c mcore_system;

-- 1. 用户账户表
CREATE TABLE IF NOT EXISTS sys_users (
    id VARCHAR(64) PRIMARY KEY,                   -- 用户全局唯一ID (如: usr_abc123)
    username VARCHAR(64) UNIQUE NOT NULL,         -- 登录用户名 / 邮箱
    password_hash VARCHAR(255) NOT NULL,          -- Argon2id / bcrypt 密码哈希
    display_name VARCHAR(128) NOT NULL DEFAULT '',-- 用户昵称
    status VARCHAR(32) NOT NULL DEFAULT 'active', -- active, suspended, deleted
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- 2. 租户数据库映射表
CREATE TABLE IF NOT EXISTS sys_tenant_databases (
    tenant_id VARCHAR(64) PRIMARY KEY REFERENCES sys_users(id) ON DELETE CASCADE,
    db_name VARCHAR(64) UNIQUE NOT NULL,          -- 物理数据库名 (如: mcore_u_usr_abc123)
    db_user VARCHAR(64) NOT NULL DEFAULT 'mcore_user',
    db_host VARCHAR(128) NOT NULL DEFAULT '127.0.0.1',
    db_port INT NOT NULL DEFAULT 5432,
    schema_version INT NOT NULL DEFAULT 1,        -- 数据库当前演进版本
    status VARCHAR(32) NOT NULL DEFAULT 'ready',  -- provisioning, ready, maintenance, archiving
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- 3. 租户安全凭证表
CREATE TABLE IF NOT EXISTS sys_tenant_api_keys (
    key_id VARCHAR(64) PRIMARY KEY,               -- 前缀标识 (如: mk_live_...)
    tenant_id VARCHAR(64) NOT NULL REFERENCES sys_users(id) ON DELETE CASCADE,
    key_hash VARCHAR(255) NOT NULL,               -- API Key 散列值
    name VARCHAR(64) NOT NULL DEFAULT 'Default Agent Key',
    allowed_scopes TEXT[] NOT NULL DEFAULT '{"read", "write"}',
    expires_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- 4. 租户配额与用量表
CREATE TABLE IF NOT EXISTS sys_tenant_quotas (
    tenant_id VARCHAR(64) PRIMARY KEY REFERENCES sys_users(id) ON DELETE CASCADE,
    max_memories INT NOT NULL DEFAULT 10000,      -- 允许最大记忆条数
    max_storage_mb INT NOT NULL DEFAULT 512,      -- 允许最大数据库体积 (MB)
    max_active_pool_size INT NOT NULL DEFAULT 3,  -- 单租户连接池上限
    current_memories INT NOT NULL DEFAULT 0,      -- 当前记忆用量缓存
    current_storage_mb REAL NOT NULL DEFAULT 0.0, -- 当前存储用量缓存
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
```

---

## 三、 数据面：模板库秒级物理克隆 (`template_mcore`)

```sql
-- 1. 创建模板库（禁止作为常规库连接）
CREATE DATABASE template_mcore WITH is_template = true OWNER mcore_user;
\c template_mcore;

-- 2. 挂载扩展与 Polyfill
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gin;
CREATE COLLATION IF NOT EXISTS nocase (provider = icu, locale = 'und-u-ks-level2', deterministic = false);

-- 执行标准 schema.sql 建表
\i /workspace/memorycore/memorycore/storage/schema.sql

-- 3. 设置只读保护
ALTER DATABASE template_mcore WITH ALLOW_CONNECTIONS false;

-- 4. 业务中新用户注册毫秒级开辟：
-- CREATE DATABASE mcore_u_<uid> TEMPLATE template_mcore OWNER mcore_user;
```
