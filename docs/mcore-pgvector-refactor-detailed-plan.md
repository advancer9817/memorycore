# MemoryCore (mcore) PostgreSQL + pgvector 彻底重构规划方案

> 目标：彻底废除 SQLite + Qdrant 双栈架构，整合为 PostgreSQL + pgvector 单一存储中枢，消除跨库双写一致性隐患、锁争用与多服务运维复杂度。

---

## 一、配置项级改动清单 (具体到字段与环境变量)

### 1. `config.yaml`
彻底移除 Qdrant 与 SQLite 配置段，新增 `database` 配置段：

```yaml
# ── 原配置项删除 ──────────────────────────────────────────
# backend:
#   primary: sqlite
#   fallback: sqlite
# qdrant:
#   url: http://127.0.0.1:6333
#   collection: agent_memory
#   timeout: 30

# ── 新增配置项 ────────────────────────────────────────────
database:
  host: "${MCORE_DB_HOST:-127.0.0.1}"
  port: 5432
  user: "${MCORE_DB_USER:-mcore}"
  password: "${MCORE_DB_PASSWORD:-mcore_secret}"
  name: "${MCORE_DB_NAME:-mcore}"
  min_pool_size: 2
  max_pool_size: 10
  timeout: 30.0
  statement_timeout_ms: 15000
  sslmode: "${MCORE_DB_SSLMODE:-prefer}"

# ── 保留并对齐的配置项 ────────────────────────────────────
embedding:
  provider: auto
  model: nomic-embed-text
  dim: 768                # 严格对齐 vector(768)
  ollama_url: http://127.0.0.1:11434
  timeout: 30
```

### 2. `pyproject.toml`
收敛依赖项：

```toml
# 移除:
# "qdrant-client>=1.18.0,<2.0",

# 新增:
dependencies = [
    "mcp>=1.27.0,<2.0",
    "pyyaml>=6.0",
    "httpx>=0.27.0",
    "psycopg[binary,pool]>=3.2.0",
    "pgvector>=0.3.0",
    "jieba>=0.42.1",
]
```

### 3. `memorycore/models.py`
- 移除 `DEFAULT_DB`（`memory.sqlite3` 路径）、`_INITIALIZED_DB_PATHS`、`sqlite3` 引用。
- 修改 `DEFAULT_CONFIG`：
  - 移除 `DEFAULT_CONFIG["backend"]` 与 `DEFAULT_CONFIG["qdrant"]`。
  - 新增 `DEFAULT_CONFIG["database"]` 字典模板。
- `validate_config(cfg)` 函数：
  - 移除对 `qdrant.url` 的 URL 格式检查。
  - 增加对 `database.host`、`database.port`、`database.user`、`database.name` 的类型与范围校验。

---

## 二、代码层文件级改动清单

| 文件路径 | 变更类型 | 改造说明 |
|---|---|---|
| `docker/docker-compose.yml` | **新增** | 提供 PG 16 + pgvector 容器编排配置，自动挂载持久化存储卷与初始化扩展。 |
| `memorycore/storage/schema.sql` | **新增** | PostgreSQL DDL 脚本：初始化扩展（`vector`, `pg_trgm`）、建表与索引。 |
| `memorycore/storage/db.py` | **彻底重写** | 移除 SQLite 锁（`_write_lock`, `_checkpoint_thread`）；引入 `psycopg_pool.ConnectionPool` 单例；提供 `get_conn()` 上下文管理器与连接健康检查。 |
| `memorycore/storage/crud.py` | **深度重构** | SQL 参数化占位符从 `?` 调整为 `%s`；`INSERT/UPDATE` 采用 `RETURNING *`；`tags` 映射为 `text[]`，`metadata` 映射为 `jsonb`。 |
| `memorycore/storage/search.py` | **深度重构** | 移除双路并发线程池与 SQLite FTS5 语法；重写为**单条 SQL 混合检索**（向量余弦距离 `<=>` 与 `pg_trgm` 相似度融合）。 |
| `memorycore/storage/entities.py` | **深度重构** | 适配 PostgreSQL 表结构与 `%s` 占位符；利用 GIN 索引加速实体反查。 |
| `memorycore/storage/profile.py` | **适配重构** | `user_profile_attrs` 读写语法适配 PG 方言与连接池。 |
| `memorycore/storage/maintenance.py` | **适配重构** | 维护计划与归档/清理逻辑改用 PG 事务与批量操作。 |
| `memorycore/storage/transfer.py` | **适配重构** | `memory_backup` 调整为导出 pg_dump / JSON 格式；`memory_rebuild_vectors` 直接更新 `embedding` 列。 |
| `memorycore/vector_store.py` | **彻底删除** | 彻底废除 Qdrant 抽象层，向量存储与检索完全内置于 PG 关系表。 |
| `scripts/reconcile_vectors.py` | **彻底删除** | 两库一致性问题已自然消失，不再需要对账脚本。 |
| `scripts/migrate_sqlite_to_pg.py` | **新增** | 一键数据迁移脚本：从 `memory.sqlite3` 与 Qdrant 提取历史全量数据灌入 PG。 |
| `memorycore/server.py` | **精简适配** | 移除 `memory_vector_status` 工具中对 Qdrant 的探测，转为探测 PG 扩展状态。 |
| `tests/conftest.py` | **基座重构** | 提供 `isolated_pg_db` fixture：测试期基于独立测试 Schema 或临时数据库运行，保障 600+ 单测隔离。 |

---

## 三、PostgreSQL 统一数据库表结构定义 (DDL)

```sql
-- 启用核心扩展
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gin;

-- 1. 记忆核心主表 (集成向量与文本索引)
CREATE TABLE IF NOT EXISTS memories (
    id UUID PRIMARY KEY,
    type VARCHAR(64) NOT NULL,
    scope VARCHAR(64) DEFAULT 'global',
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT[] DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    source VARCHAR(64) DEFAULT 'manual',
    source_agent VARCHAR(64) DEFAULT 'agent',
    project_path TEXT DEFAULT '',
    
    -- 度量与治理评分
    confidence REAL DEFAULT 0.70,
    importance REAL DEFAULT 0.50,
    status VARCHAR(32) DEFAULT 'active',
    decay_policy VARCHAR(32) DEFAULT 'review',
    feedback_score REAL DEFAULT 0.0,
    injected_count INT DEFAULT 0,
    ineffective_count INT DEFAULT 0,
    effectiveness_score REAL DEFAULT 0.50,
    
    -- 时间与血缘
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    last_accessed_at TIMESTAMPTZ,
    last_injected_at TIMESTAMPTZ,
    valid_from TIMESTAMPTZ,
    valid_until TIMESTAMPTZ,
    superseded_by UUID,
    fact_lineage_root UUID,
    
    -- 原生向量字段 (768 维)
    embedding vector(768)
);

-- 索引架构
CREATE INDEX IF NOT EXISTS idx_memories_embedding ON memories USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_memories_trgm ON memories USING gin ((title || ' ' || content) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_memories_tags ON memories USING gin (tags);
CREATE INDEX IF NOT EXISTS idx_memories_metadata ON memories USING gin (metadata);
CREATE INDEX IF NOT EXISTS idx_memories_status_type ON memories (status, type);
CREATE INDEX IF NOT EXISTS idx_memories_updated_at ON memories (updated_at DESC);

-- 2. 知识图谱关联表
CREATE TABLE IF NOT EXISTS memory_links (
    id SERIAL PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    target_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    relation_type VARCHAR(64) NOT NULL,
    weight REAL DEFAULT 1.0,
    note TEXT DEFAULT '',
    source_agent VARCHAR(64) DEFAULT 'agent',
    created_at TIMESTAMPTZ DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ DEFAULT clock_timestamp(),
    UNIQUE (source_id, target_id, relation_type)
);

-- 3. 实体别名索引表
CREATE TABLE IF NOT EXISTS memory_entities (
    id SERIAL PRIMARY KEY,
    memory_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    entity TEXT NOT NULL,
    normalized_entity TEXT NOT NULL,
    entity_type VARCHAR(64) NOT NULL,
    weight REAL DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT clock_timestamp(),
    UNIQUE (memory_id, normalized_entity, entity_type)
);
CREATE INDEX IF NOT EXISTS idx_entities_normalized ON memory_entities (normalized_entity);

-- 4. 用户画像属性表
CREATE TABLE IF NOT EXISTS user_profile_attrs (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL DEFAULT 'default',
    attribute VARCHAR(128) NOT NULL,
    value TEXT NOT NULL,
    confidence REAL DEFAULT 0.70,
    immutable BOOLEAN DEFAULT FALSE,
    last_updated TIMESTAMPTZ DEFAULT clock_timestamp(),
    decay_days INT DEFAULT 30,
    UNIQUE (user_id, attribute)
);

-- 5. 反馈事件与上下文质量表
CREATE TABLE IF NOT EXISTS feedback_events (
    id SERIAL PRIMARY KEY,
    memory_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    score REAL NOT NULL,
    note TEXT DEFAULT '',
    source_agent VARCHAR(64) DEFAULT 'agent',
    created_at TIMESTAMPTZ DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS context_quality_events (
    id SERIAL PRIMARY KEY,
    task TEXT NOT NULL,
    task_type VARCHAR(64) DEFAULT 'general',
    agent VARCHAR(64) DEFAULT 'agent',
    project_path TEXT DEFAULT '',
    scope VARCHAR(64) DEFAULT 'global',
    total_candidates INT DEFAULT 0,
    used_count INT DEFAULT 0,
    filtered_count INT DEFAULT 0,
    hit_rate REAL DEFAULT 0.0,
    filter_rate REAL DEFAULT 0.0,
    cross_retrieval_rate REAL DEFAULT 0.0,
    vector_avg_score REAL DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT clock_timestamp()
);

-- 6. 治理与审核日志表
CREATE TABLE IF NOT EXISTS governance_decisions (
    id UUID PRIMARY KEY,
    decision_type VARCHAR(64) NOT NULL,
    source_ids UUID[] NOT NULL,
    recommended_action VARCHAR(64) NOT NULL,
    status VARCHAR(32) DEFAULT 'pending',
    finding JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS curator_review_log (
    id SERIAL PRIMARY KEY,
    memory_id UUID NOT NULL,
    curator_type VARCHAR(32) NOT NULL,
    reviewed_at TIMESTAMPTZ DEFAULT clock_timestamp()
);
```

---

## 四、混合检索单 SQL 化实现细节

在 `memorycore/storage/search.py` 中，彻底替换原有内存归并逻辑，直接由数据库执行加权混合检索：

```python
def hybrid_search_records(
    conn: psycopg.Connection,
    query_text: str,
    query_vector: list[float] | None,
    scope: str = "",
    project_path: str = "",
    status: str = "active",
    limit: int = 10,
    vector_weight: float = 0.45,
    text_weight: float = 0.35,
    importance_weight: float = 0.20,
) -> list[dict[str, Any]]:
    # 单条 SQL 融合 pgvector 与 pg_trgm
    sql = """
    WITH matched AS (
        SELECT m.id, m.type, m.title, m.content, m.tags, m.updated_at, m.project_path,
               m.importance, m.effectiveness_score,
               CASE 
                   WHEN %(vector)s IS NOT NULL AND m.embedding IS NOT NULL 
                   THEN 1 - (m.embedding <=> %(vector)s::vector)
                   ELSE 0.0 
               END AS vec_score,
               similarity(m.title || ' ' || m.content, %(query)s) AS trgm_score
        FROM memories m
        WHERE m.status = %(status)s
          AND (%(scope)s = '' OR m.scope = %(scope)s OR m.scope = 'global')
          AND (%(project_path)s = '' OR m.project_path = %(project_path)s OR m.project_path = '')
          AND (m.valid_until IS NULL OR m.valid_until > clock_timestamp())
    )
    SELECT id, type, title, content, tags, updated_at, project_path,
           vec_score, trgm_score,
           (vec_score * %(w_vec)s + trgm_score * %(w_text)s + importance * %(w_imp)s) AS rank_score
    FROM matched
    WHERE vec_score >= 0.35 OR trgm_score >= 0.10
    ORDER BY rank_score DESC
    LIMIT %(limit)s;
    """
    params = {
        "query": query_text,
        "vector": query_vector,
        "status": status,
        "scope": scope,
        "project_path": project_path,
        "limit": limit,
        "w_vec": vector_weight,
        "w_text": text_weight,
        "w_imp": importance_weight,
    }
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()
```

---

## 五、无损数据迁移规划 (`scripts/migrate_sqlite_to_pg.py`)

1. **结构化数据提取**：从 `memory.sqlite3` 直连读出全部行记录。
2. **Qdrant 向量直通同步**：
   - 连接正在运行的 Qdrant（`127.0.0.1:6333`）；
   - 根据记录 ID 批量获取已有 `point.vector`；
   - **已有向量直接复用**灌入 PG 的 `embedding` 字段，规避 4,800+ 条记录耗时数小时的重新嵌入计算；
   - 仅对 Qdrant 中缺失向量的记录调用本地 Ollama 补齐。
3. **外键约束与数据一致性校验**：
   - 先导入主表 `memories`；
   - 再批量导入 `memory_links`、`memory_entities`、`user_profile_attrs`、`feedback_events`；
   - 自动核对行数一致性。

---

## 六、部署与服务纳管规划

1. **Docker Compose 配置 (`docker/docker-compose.yml`)**：
   ```yaml
   services:
     postgres:
       image: ankane/pgvector:v0.5.1
       container_name: mcore-postgres
       restart: always
       environment:
         POSTGRES_DB: mcore
         POSTGRES_USER: mcore
         POSTGRES_PASSWORD: mcore_secret
       ports:
         - "127.0.0.1:5432:5432"
       volumes:
         - ./data/postgres:/var/lib/postgresql/data
   ```
2. **停用下线 Qdrant**：
   - 验证数据全量导入 PG 且检索测试通过后，停止并销毁 Qdrant 容器；
   - 释放端口 6333/6334。
3. **systemd 服务配置适配**：
   - `mcore.service` 环境变量中加入 `MCORE_DB_HOST=127.0.0.1` 等连接串配置；
   - 重启验证服务健康检查。
