package org.mcore.storage.repository;

import org.mcore.common.model.MemoryDO;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * 基于 JdbcClient 的多租户记忆持久化访问仓储
 * 自动随当前线程上下文动态路由至对应租户的物理数据库
 */
@Repository
public class MemoryRepository {

    private final JdbcClient jdbcClient;

    public MemoryRepository(JdbcClient jdbcClient) {
        this.jdbcClient = jdbcClient;
    }

    public long countActiveMemories() {
        return jdbcClient.sql("SELECT count(*) FROM memories WHERE status = 'active'")
                .query(Long.class)
                .single();
    }

    public Optional<MemoryDO> findById(String id) {
        String sql = "SELECT id, type, scope, title, content, source, source_agent, status, " +
                     "importance, confidence, effectiveness_score AS effectiveness, injected_count AS access_count, created_at, updated_at " +
                     "FROM memories WHERE id = :id";
        return jdbcClient.sql(sql)
                .param("id", id)
                .query((rs, rowNum) -> {
                    MemoryDO mem = new MemoryDO();
                    mem.setId(rs.getString("id"));
                    mem.setType(rs.getString("type"));
                    mem.setScope(rs.getString("scope"));
                    mem.setTitle(rs.getString("title"));
                    mem.setContent(rs.getString("content"));
                    mem.setSource(rs.getString("source"));
                    mem.setSourceAgent(rs.getString("source_agent"));
                    mem.setStatus(rs.getString("status"));
                    mem.setImportance(rs.getDouble("importance"));
                    mem.setConfidence(rs.getDouble("confidence"));
                    mem.setEffectiveness(rs.getDouble("effectiveness"));
                    mem.setAccessCount(rs.getInt("access_count"));
                    Timestamp cAt = rs.getTimestamp("created_at");
                    if (cAt != null) mem.setCreatedAt(cAt.toInstant());
                    Timestamp uAt = rs.getTimestamp("updated_at");
                    if (uAt != null) mem.setUpdatedAt(uAt.toInstant());
                    return mem;
                })
                .optional();
    }

    public List<MemoryDO> listRecent(int limit) {
        String sql = "SELECT id, type, scope, title, content, source, source_agent, status, " +
                     "importance, confidence, effectiveness_score AS effectiveness, injected_count AS access_count, created_at, updated_at " +
                     "FROM memories WHERE status = 'active' ORDER BY created_at DESC LIMIT :limit";
        return jdbcClient.sql(sql)
                .param("limit", limit)
                .query((rs, rowNum) -> {
                    MemoryDO mem = new MemoryDO();
                    mem.setId(rs.getString("id"));
                    mem.setType(rs.getString("type"));
                    mem.setScope(rs.getString("scope"));
                    mem.setTitle(rs.getString("title"));
                    mem.setContent(rs.getString("content"));
                    mem.setSource(rs.getString("source"));
                    mem.setSourceAgent(rs.getString("source_agent"));
                    mem.setStatus(rs.getString("status"));
                    mem.setImportance(rs.getDouble("importance"));
                    mem.setConfidence(rs.getDouble("confidence"));
                    mem.setEffectiveness(rs.getDouble("effectiveness"));
                    mem.setAccessCount(rs.getInt("access_count"));
                    Timestamp cAt = rs.getTimestamp("created_at");
                    if (cAt != null) mem.setCreatedAt(cAt.toInstant());
                    Timestamp uAt = rs.getTimestamp("updated_at");
                    if (uAt != null) mem.setUpdatedAt(uAt.toInstant());
                    return mem;
                })
                .list();
    }

    public void insert(MemoryDO record) {
        String sql = """
            INSERT INTO memories (
                id, type, scope, title, content, source, source_agent, status,
                importance, confidence, effectiveness_score, injected_count, created_at, updated_at
            ) VALUES (
                :id, :type, :scope, :title, :content, :source, :sourceAgent, :status,
                :importance, :confidence, :effectiveness, 0, clock_timestamp(), clock_timestamp()
            )
        """;
        jdbcClient.sql(sql)
                .param("id", record.getId())
                .param("type", record.getType() != null ? record.getType() : "core_fact")
                .param("scope", record.getScope() != null ? record.getScope() : "global")
                .param("title", record.getTitle() != null ? record.getTitle() : "")
                .param("content", record.getContent())
                .param("source", record.getSource() != null ? record.getSource() : "manual")
                .param("sourceAgent", record.getSourceAgent() != null ? record.getSourceAgent() : "system")
                .param("status", record.getStatus() != null ? record.getStatus() : "active")
                .param("importance", record.getImportance() != null ? record.getImportance() : 0.5)
                .param("confidence", record.getConfidence() != null ? record.getConfidence() : 0.8)
                .param("effectiveness", record.getEffectiveness() != null ? record.getEffectiveness() : 0.5)
                .update();
    }

    public boolean update(String id, String content, Double importance, String status) {
        StringBuilder sql = new StringBuilder("UPDATE memories SET updated_at = clock_timestamp()");
        if (content != null && !content.isBlank()) sql.append(", content = :content");
        if (importance != null) sql.append(", importance = :importance");
        if (status != null && !status.isBlank()) sql.append(", status = :status");
        sql.append(" WHERE id = :id");

        var spec = jdbcClient.sql(sql.toString()).param("id", id);
        if (content != null && !content.isBlank()) spec.param("content", content);
        if (importance != null) spec.param("importance", importance);
        if (status != null && !status.isBlank()) spec.param("status", status);
        return spec.update() > 0;
    }

    public boolean supersede(String oldId, String newId) {
        String sql = "UPDATE memories SET status = 'superseded', superseded_by = :newId, updated_at = clock_timestamp() WHERE id = :oldId";
        return jdbcClient.sql(sql).param("oldId", oldId).param("newId", newId).update() > 0;
    }

    public void addFeedback(String memoryId, double score, String note, String agent) {
        String sql = """
            INSERT INTO feedback_events (id, memory_id, score, note, source_agent, created_at)
            VALUES (:id, :memoryId, :score, :note, :agent, clock_timestamp())
        """;
        jdbcClient.sql(sql)
                .param("id", "fb_" + java.util.UUID.randomUUID().toString().replace("-", "").substring(0, 16))
                .param("memoryId", memoryId)
                .param("score", score)
                .param("note", note != null ? note : "")
                .param("agent", agent != null ? agent : "agent")
                .update();
    }

    public void addLink(String sourceId, String targetId, String relationType, String agent) {
        String sql = """
            INSERT INTO memory_links (id, source_id, target_id, relation_type, weight, note, source_agent, created_at, updated_at)
            VALUES (:id, :sourceId, :targetId, :rel, 1.0, '', :agent, clock_timestamp(), clock_timestamp())
            ON CONFLICT (source_id, target_id, relation_type) DO NOTHING
        """;
        jdbcClient.sql(sql)
                .param("id", "lnk_" + java.util.UUID.randomUUID().toString().replace("-", "").substring(0, 16))
                .param("sourceId", sourceId)
                .param("targetId", targetId)
                .param("rel", relationType != null ? relationType : "related_to")
                .param("agent", agent != null ? agent : "agent")
                .update();
    }

    public List<java.util.Map<String, Object>> listLinks(String memoryId) {
        String sql = """
            SELECT l.id, l.source_id, l.target_id, l.relation_type, l.weight, l.note, l.created_at
            FROM memory_links l
            WHERE l.source_id = :mid OR l.target_id = :mid
        """;
        return jdbcClient.sql(sql).param("mid", memoryId).query().listOfRows();
    }

    public List<java.util.Map<String, Object>> searchEntities(String query) {
        String sql = """
            SELECT e.entity, e.normalized_entity, e.entity_type, e.memory_id, m.title, m.content
            FROM memory_entities e
            JOIN memories m ON e.memory_id = m.id
            WHERE e.normalized_entity LIKE :pattern
            LIMIT 20
        """;
        return jdbcClient.sql(sql).param("pattern", "%" + query.toLowerCase() + "%").query().listOfRows();
    }

    public List<java.util.Map<String, Object>> listAuditLogs(int limit) {
        String sql = "SELECT id, event_type, memory_id, agent, created_at FROM audit_events ORDER BY created_at DESC LIMIT :limit";
        return jdbcClient.sql(sql).param("limit", limit > 0 ? limit : 20).query().listOfRows();
    }

    public List<java.util.Map<String, Object>> listWarnings() {
        String sql = "SELECT id, title, status, updated_at FROM memories WHERE status IN ('stale', 'contradicted') LIMIT 20";
        return jdbcClient.sql(sql).query().listOfRows();
    }
}
