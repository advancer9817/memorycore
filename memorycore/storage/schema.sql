-- MemoryCore PostgreSQL 16 + pgvector Complete Schema DDL
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gin;
CREATE COLLATION IF NOT EXISTS nocase (provider = icu, locale = 'und-u-ks-level2', deterministic = false);

-- SQLite json_extract polyfill for JSONB and TEXT columns
CREATE OR REPLACE FUNCTION json_extract(doc jsonb, path text)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT doc #>> string_to_array(trim(leading '$.' from path), '.');
$$;

CREATE OR REPLACE FUNCTION json_extract(doc text, path text)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT (doc::jsonb) #>> string_to_array(trim(leading '$.' from path), '.');
$$;

-- SQLite datetime polyfills
CREATE OR REPLACE FUNCTION datetime(ts text)
RETURNS timestamptz LANGUAGE sql IMMUTABLE AS $$
    SELECT ts::timestamptz;
$$;

CREATE OR REPLACE FUNCTION datetime(ts timestamptz)
RETURNS timestamptz LANGUAGE sql IMMUTABLE AS $$
    SELECT ts;
$$;

CREATE OR REPLACE FUNCTION datetime(base text, time_offset text)
RETURNS timestamptz LANGUAGE plpgsql STABLE AS $$
BEGIN
    IF base = 'now' THEN
        RETURN now() + time_offset::interval;
    ELSE
        RETURN base::timestamptz + time_offset::interval;
    END IF;
END;
$$;

-- SQLite group_concat polyfill
CREATE OR REPLACE FUNCTION group_concat_state(state text, val text)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN state IS NULL THEN val ELSE state || ',' || val END;
$$;

CREATE OR REPLACE AGGREGATE group_concat(text) (
    SFUNC = group_concat_state,
    STYPE = text
);

-- 1. memories: Core memory storage with native 768-dim vector embedding
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    type VARCHAR(64) NOT NULL,
    scope VARCHAR(64) NOT NULL DEFAULT 'global',
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT[] NOT NULL DEFAULT '{}',
    metadata JSONB NOT NULL DEFAULT '{}',
    source VARCHAR(64) NOT NULL DEFAULT 'manual',
    source_agent VARCHAR(64) NOT NULL DEFAULT 'agent',
    project_path TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.70,
    importance REAL NOT NULL DEFAULT 0.50,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    decay_policy VARCHAR(32) NOT NULL DEFAULT 'review',
    feedback_score REAL NOT NULL DEFAULT 0.0,
    injected_count INT NOT NULL DEFAULT 0,
    ineffective_count INT NOT NULL DEFAULT 0,
    effectiveness_score REAL NOT NULL DEFAULT 0.50,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    last_accessed_at TIMESTAMPTZ,
    last_injected_at TIMESTAMPTZ,
    valid_from TEXT,
    valid_until TEXT,
    superseded_by TEXT,
    fact_lineage_root TEXT,
    related_ids TEXT[] NOT NULL DEFAULT '{}',
    tags_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    related_ids_json TEXT NOT NULL DEFAULT '[]',
    embedding vector(768)
);

CREATE OR REPLACE FUNCTION sync_memories_json_columns()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.tags_json IS NOT NULL AND (NEW.tags IS NULL OR NEW.tags = '{}' OR NEW.tags_json != '[]') THEN
        BEGIN
            NEW.tags := ARRAY(SELECT json_array_elements_text(NEW.tags_json::json));
        EXCEPTION WHEN OTHERS THEN
            NULL;
        END;
    ELSIF NEW.tags IS NOT NULL AND (NEW.tags_json IS NULL OR NEW.tags_json = '[]') THEN
        NEW.tags_json := to_json(NEW.tags)::text;
    END IF;

    IF NEW.metadata_json IS NOT NULL AND (NEW.metadata IS NULL OR NEW.metadata = '{}'::jsonb OR NEW.metadata_json != '{}') THEN
        BEGIN
            NEW.metadata := NEW.metadata_json::jsonb;
        EXCEPTION WHEN OTHERS THEN
            NULL;
        END;
    ELSIF NEW.metadata IS NOT NULL AND (NEW.metadata_json IS NULL OR NEW.metadata_json = '{}') THEN
        NEW.metadata_json := NEW.metadata::text;
    END IF;

    IF NEW.related_ids_json IS NOT NULL AND (NEW.related_ids IS NULL OR NEW.related_ids = '{}' OR NEW.related_ids_json != '[]') THEN
        BEGIN
            NEW.related_ids := ARRAY(SELECT json_array_elements_text(NEW.related_ids_json::json));
        EXCEPTION WHEN OTHERS THEN
            NULL;
        END;
    ELSIF NEW.related_ids IS NOT NULL AND (NEW.related_ids_json IS NULL OR NEW.related_ids_json = '[]') THEN
        NEW.related_ids_json := to_json(NEW.related_ids)::text;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sync_memories_json ON memories;
CREATE TRIGGER trg_sync_memories_json
BEFORE INSERT OR UPDATE ON memories
FOR EACH ROW EXECUTE FUNCTION sync_memories_json_columns();

CREATE INDEX IF NOT EXISTS idx_memories_embedding ON memories USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_memories_trgm ON memories USING gin ((title || ' ' || content) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_memories_tags ON memories USING gin (tags);
CREATE INDEX IF NOT EXISTS idx_memories_metadata ON memories USING gin (metadata);
CREATE INDEX IF NOT EXISTS idx_memories_status_type ON memories (status, type);
CREATE INDEX IF NOT EXISTS idx_memories_scope_path ON memories (scope, project_path);
CREATE INDEX IF NOT EXISTS idx_memories_updated_at ON memories (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_superseded_by ON memories (superseded_by);
CREATE INDEX IF NOT EXISTS idx_memories_lineage_root ON memories (fact_lineage_root);
CREATE INDEX IF NOT EXISTS idx_memories_status_lineage ON memories (status, fact_lineage_root);

CREATE OR REPLACE VIEW memories_fts AS
SELECT id, title, content, tags_json as tags, type, scope FROM memories;

-- 2. memory_links: Knowledge graph relationships
CREATE TABLE IF NOT EXISTS memory_links (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    relation_type VARCHAR(64) NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    note TEXT NOT NULL DEFAULT '',
    source_agent VARCHAR(64) NOT NULL DEFAULT 'agent',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (source_id, target_id, relation_type)
);
CREATE INDEX IF NOT EXISTS idx_links_target ON memory_links (target_id);

-- 3. memory_entities: Entity index and alias map
CREATE TABLE IF NOT EXISTS memory_entities (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    entity TEXT NOT NULL,
    normalized_entity TEXT NOT NULL,
    aliases_json JSONB NOT NULL DEFAULT '[]',
    entity_type VARCHAR(64) NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (memory_id, normalized_entity)
);
CREATE INDEX IF NOT EXISTS idx_entities_normalized ON memory_entities (normalized_entity);

-- 4. user_profile_attrs: User profile facts and settings
CREATE TABLE IF NOT EXISTS user_profile_attrs (
    user_id VARCHAR(64) NOT NULL DEFAULT 'default',
    attribute VARCHAR(128) NOT NULL,
    value TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.70,
    immutable INT NOT NULL DEFAULT 0,
    source_ids_json JSONB NOT NULL DEFAULT '[]',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    decayed_at TIMESTAMPTZ,
    PRIMARY KEY (user_id, attribute)
);

-- 5. feedback_events: Feedback events
CREATE TABLE IF NOT EXISTS feedback_events (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    score REAL NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    source_agent VARCHAR(64) NOT NULL DEFAULT 'agent',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- 6. context_quality_events: Context pack quality metrics
CREATE TABLE IF NOT EXISTS context_quality_events (
    id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    task_type VARCHAR(64) NOT NULL DEFAULT 'general',
    agent VARCHAR(64) NOT NULL DEFAULT 'agent',
    project_path TEXT NOT NULL DEFAULT '',
    scope VARCHAR(64) NOT NULL DEFAULT 'global',
    total_candidates INT NOT NULL DEFAULT 0,
    used_count INT NOT NULL DEFAULT 0,
    filtered_count INT NOT NULL DEFAULT 0,
    hit_rate REAL NOT NULL DEFAULT 0.0,
    filter_rate REAL NOT NULL DEFAULT 0.0,
    ineffective_rate REAL NOT NULL DEFAULT 0.0,
    type_weights_json JSONB NOT NULL DEFAULT '{}',
    vector_avg_score REAL NOT NULL DEFAULT 0.0,
    cross_retrieval_rate REAL NOT NULL DEFAULT 0.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- 7. governance_decisions: LLM curator decisions
CREATE TABLE IF NOT EXISTS governance_decisions (
    id TEXT PRIMARY KEY,
    decision_type VARCHAR(64) NOT NULL,
    source_ids_json JSONB NOT NULL DEFAULT '[]',
    recommended_action VARCHAR(64) NOT NULL,
    llm_confidence REAL,
    risk_level VARCHAR(32),
    review_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    policy_reason TEXT,
    finding_json JSONB NOT NULL DEFAULT '{}',
    llm_trace_json JSONB NOT NULL DEFAULT '{}',
    raw_response_ref TEXT,
    before_state_json JSONB,
    after_state_json JSONB,
    rollback_json JSONB,
    source_agent VARCHAR(64) NOT NULL DEFAULT 'agent',
    candidate_hash TEXT,
    policy_reasons_json JSONB NOT NULL DEFAULT '[]',
    policy_version VARCHAR(32),
    judge_model VARCHAR(64),
    judge_schema_version VARCHAR(32),
    decision_version VARCHAR(32),
    execution_id TEXT,
    applied_by VARCHAR(64),
    rolled_back_by VARCHAR(64),
    approval_kind VARCHAR(32),
    curator_job_id TEXT,
    curator_batch_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    applied_at TIMESTAMPTZ,
    rolled_back_at TIMESTAMPTZ
);

-- 8. curator_review_log & jobs
CREATE TABLE IF NOT EXISTS curator_review_log (
    memory_id TEXT NOT NULL,
    review_type VARCHAR(32) NOT NULL DEFAULT 'llm_curator',
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(memory_id, review_type)
);

CREATE TABLE IF NOT EXISTS llm_curator_jobs (
    id TEXT PRIMARY KEY,
    status VARCHAR(32) NOT NULL DEFAULT 'running',
    params_json JSONB NOT NULL DEFAULT '{}',
    progress_json JSONB NOT NULL DEFAULT '{}',
    summary_json JSONB NOT NULL DEFAULT '{}',
    error_json JSONB NOT NULL DEFAULT '{}',
    governance_run_id TEXT,
    created_by VARCHAR(64),
    started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS llm_curator_batches (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    stage VARCHAR(64) NOT NULL,
    batch_index INT NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'running',
    candidate_count INT NOT NULL DEFAULT 0,
    finding_count INT NOT NULL DEFAULT 0,
    decision_count INT NOT NULL DEFAULT 0,
    cursor_token TEXT,
    error_json JSONB NOT NULL DEFAULT '{}',
    started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS maintenance_jobs (
    id TEXT PRIMARY KEY,
    plan_token TEXT NOT NULL,
    kind VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'running',
    summary_json JSONB NOT NULL DEFAULT '{}',
    backup_path TEXT,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    event_type VARCHAR(64) NOT NULL,
    memory_id TEXT,
    agent VARCHAR(64) NOT NULL DEFAULT 'agent',
    detail_json JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- 13. vector_cache: Embeddings cache
CREATE TABLE IF NOT EXISTS vector_cache (
    text_hash TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    vector_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (text_hash, model)
);

-- 14. vector_sync_queue: Background sync queue
CREATE TABLE IF NOT EXISTS vector_sync_queue (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    operation VARCHAR(32) NOT NULL DEFAULT 'upsert',
    retry_count INT NOT NULL DEFAULT 0,
    max_retries INT NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL,
    last_attempt_at TEXT,
    error TEXT
);

-- 15. agent_presence & agent_messages
CREATE TABLE IF NOT EXISTS agent_presence (
    agent_id TEXT PRIMARY KEY,
    status VARCHAR(32) NOT NULL DEFAULT 'offline',
    last_seen_at TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS agent_messages (
    id TEXT PRIMARY KEY,
    from_agent VARCHAR(64) NOT NULL,
    to_agent VARCHAR(64) NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    priority VARCHAR(32) NOT NULL DEFAULT 'normal',
    status VARCHAR(32) NOT NULL DEFAULT 'unread',
    created_at TEXT NOT NULL,
    read_at TEXT,
    metadata_json JSONB NOT NULL DEFAULT '{}',
    expires_at TEXT
);

-- 16. schema_version
CREATE TABLE IF NOT EXISTS schema_version (
    version INT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- 17. governance_runs, executions and mutation_log
CREATE TABLE IF NOT EXISTS governance_runs (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    mode TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    summary_json JSONB,
    error_json JSONB,
    created_by TEXT NOT NULL,
    metadata_json JSONB
);
CREATE INDEX IF NOT EXISTS idx_governance_runs_source_status ON governance_runs(source, status);

CREATE TABLE IF NOT EXISTS governance_executions (
    id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES governance_runs(id) ON DELETE SET NULL,
    decision_id TEXT REFERENCES governance_decisions(id) ON DELETE SET NULL,
    approval_kind TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    status TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    policy_snapshot_json JSONB NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error_json JSONB,
    created_by TEXT NOT NULL,
    metadata_json JSONB
);
CREATE INDEX IF NOT EXISTS idx_governance_executions_run_id ON governance_executions(run_id);
CREATE INDEX IF NOT EXISTS idx_governance_executions_decision_id ON governance_executions(decision_id);
CREATE INDEX IF NOT EXISTS idx_governance_executions_status ON governance_executions(status);

CREATE TABLE IF NOT EXISTS governance_mutation_log (
    id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL REFERENCES governance_executions(id) ON DELETE CASCADE,
    seq INT NOT NULL,
    mutation_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    operation TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    policy_decision TEXT NOT NULL,
    policy_reason TEXT,
    request_json JSONB NOT NULL DEFAULT '{}',
    before_json JSONB,
    after_json JSONB,
    inverse_json JSONB,
    index_effect_json JSONB,
    status TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    applied_at TEXT,
    rolled_back_at TEXT,
    error_json JSONB
);
CREATE INDEX IF NOT EXISTS idx_governance_mutation_log_execution ON governance_mutation_log(execution_id, seq);
CREATE INDEX IF NOT EXISTS idx_governance_mutation_log_entity ON governance_mutation_log(entity_type, entity_id);

CREATE TABLE IF NOT EXISTS agent_capabilities (
    agent_id TEXT PRIMARY KEY,
    namespace TEXT NOT NULL DEFAULT 'default',
    capabilities_json JSONB NOT NULL DEFAULT '[]',
    metadata_json JSONB NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
