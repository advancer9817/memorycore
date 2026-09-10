-- MemoryCore System Metadata Database Schema
-- Table definitions for control plane

CREATE TABLE IF NOT EXISTS sys_users (
    id VARCHAR(64) PRIMARY KEY,                   -- 用户全局唯一ID (如: default, usr_abc123)
    username VARCHAR(64) UNIQUE NOT NULL,         -- 登录用户名 / 邮箱
    password_hash VARCHAR(255) NOT NULL,          -- Argon2id / bcrypt 密码哈希
    display_name VARCHAR(128) NOT NULL DEFAULT '',-- 用户昵称
    status VARCHAR(32) NOT NULL DEFAULT 'active', -- active, suspended, deleted
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS sys_tenant_databases (
    tenant_id VARCHAR(64) PRIMARY KEY REFERENCES sys_users(id) ON DELETE CASCADE,
    db_name VARCHAR(64) UNIQUE NOT NULL,          -- 物理数据库名 (如: mcore, mcore_u_usr_abc123)
    db_user VARCHAR(64) NOT NULL DEFAULT 'mcore_user',
    db_host VARCHAR(128) NOT NULL DEFAULT '127.0.0.1',
    db_port INT NOT NULL DEFAULT 5432,
    schema_version INT NOT NULL DEFAULT 1,        -- 数据库当前演进版本
    status VARCHAR(32) NOT NULL DEFAULT 'ready',  -- provisioning, ready, maintenance, archiving
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

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

CREATE TABLE IF NOT EXISTS sys_tenant_quotas (
    tenant_id VARCHAR(64) PRIMARY KEY REFERENCES sys_users(id) ON DELETE CASCADE,
    max_memories INT NOT NULL DEFAULT 10000,      -- 允许最大记忆条数
    max_storage_mb INT NOT NULL DEFAULT 512,      -- 允许最大数据库体积 (MB)
    max_active_pool_size INT NOT NULL DEFAULT 3,  -- 单租户连接池上限
    current_memories INT NOT NULL DEFAULT 0,      -- 当前记忆用量缓存
    current_storage_mb REAL NOT NULL DEFAULT 0.0, -- 当前存储用量缓存
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Seed default tenant pointing to the existing 'mcore' database
INSERT INTO sys_users (id, username, password_hash, display_name)
VALUES ('default', 'default_admin', '$2a$10$default_placeholder_hash', 'Default Administrator')
ON CONFLICT (id) DO NOTHING;

INSERT INTO sys_tenant_databases (tenant_id, db_name, db_user, db_host, db_port, schema_version, status)
VALUES ('default', 'mcore', 'mcore_user', '127.0.0.1', 5432, 1, 'ready')
ON CONFLICT (tenant_id) DO NOTHING;

INSERT INTO sys_tenant_quotas (tenant_id, max_memories, max_storage_mb, max_active_pool_size, current_memories)
VALUES ('default', 50000, 2048, 5, 4641)
ON CONFLICT (tenant_id) DO NOTHING;
