package org.mcore.storage.search;

import com.pgvector.PGvector;
import org.mcore.common.model.MemoryDO;
import org.mcore.storage.embedding.EmbeddingService;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.sql.Timestamp;
import java.util.List;

/**
 * 单阶段（Single-Pass）真正双模单 SQL 混合检索引擎
 * 融合 768 维 pgvector 余弦距离 (<=>) 与 pg_trgm 三元词相似度 (similarity)
 */
@Service
public class HybridSearchService {

    private final JdbcClient jdbcClient;
    private final EmbeddingService embeddingService;

    public record SearchHit(MemoryDO record, double finalScore, double vectorScore, double textScore) {}

    public HybridSearchService(JdbcClient jdbcClient, EmbeddingService embeddingService) {
        this.jdbcClient = jdbcClient;
        this.embeddingService = embeddingService;
    }

    /**
     * 自动向量化并执行混合检索
     */
    public List<SearchHit> hybridSearch(String query, String type, int limit) {
        if (embeddingService.isRealModelOnline()) {
            float[] queryVec = embeddingService.embedText(query);
            return hybridSearch(query, queryVec, type, limit);
        } else {
            // 语义模型离线处于伪哈希降级时，直接走纯文本三元词检索，避免随机哈希噪声污染
            return hybridSearch(query, null, type, limit);
        }
    }

    /**
     * 纯向量余弦距离检索 (供 memory_vector_search 工具使用)
     */
    public List<SearchHit> pureVectorSearch(String query, int limit) {
        float[] queryVec = embeddingService.embedText(query);
        return pureVectorSearch(queryVec, limit);
    }

    /**
     * 基于已计算的特征向量执行纯向量余弦距离检索
     */
    public List<SearchHit> pureVectorSearch(float[] queryVec, int limit) {
        if (queryVec == null || queryVec.length == 0) {
            return List.of();
        }
        PGvector vec = new PGvector(queryVec);
        int fetchLimit = limit > 0 ? limit : 10;

        String sql = """
            SELECT m.*,
                   (1.0 - (m.embedding <=> :vec)) AS vector_sim,
                   0.0 AS text_sim,
                   (1.0 - (m.embedding <=> :vec)) AS final_score
            FROM memories m
            WHERE m.status = 'active' AND m.embedding IS NOT NULL
            ORDER BY m.embedding <=> :vec ASC
            LIMIT :limit
        """;

        return jdbcClient.sql(sql)
                .param("vec", vec)
                .param("limit", fetchLimit)
                .query((rs, rowNum) -> mapRow(rs))
                .list();
    }

    public List<SearchHit> hybridSearch(String query, float[] embedding, String type, int limit) {
        PGvector vec = (embedding != null && embedding.length > 0) ? new PGvector(embedding) : null;
        int fetchLimit = limit > 0 ? limit : 10;
        String q = query != null ? query : "";
        String t = (type != null && !type.isBlank()) ? type.trim() : null;

        if (vec != null) {
            String sql = """
                SELECT m.*,
                    (CASE WHEN m.embedding IS NOT NULL THEN (1.0 - (m.embedding <=> :vec)) ELSE 0.0 END) AS vector_sim,
                    similarity(m.title || ' ' || m.content, :query) AS text_sim,
                    (
                        (GREATEST(
                            (CASE WHEN m.embedding IS NOT NULL THEN (1.0 - (m.embedding <=> :vec)) ELSE 0.0 END),
                            similarity(m.title || ' ' || m.content, :query)
                        ) * 0.70) +
                        (similarity(m.title || ' ' || m.content, :query) * 0.15) +
                        (COALESCE(m.importance, 0.5) * 0.15)
                    ) AS final_score
                FROM memories m
                WHERE m.status = 'active'
            """ + (t != null ? " AND m.type = :type " : "") + """
                  AND (
                      (m.embedding IS NOT NULL AND (m.embedding <=> :vec) < 0.60) OR
                      (similarity(m.title || ' ' || m.content, :query) > 0.03) OR
                      (:query = '')
                  )
                ORDER BY final_score DESC
                LIMIT :limit
            """;

            var spec = jdbcClient.sql(sql)
                    .param("vec", vec)
                    .param("query", q)
                    .param("limit", fetchLimit);
            if (t != null) {
                spec.param("type", t);
            }
            return spec.query((rs, rowNum) -> mapRow(rs)).list();
        } else {
            String sql = """
                SELECT m.*,
                    0.0 AS vector_sim,
                    similarity(m.title || ' ' || m.content, :query) AS text_sim,
                    (
                        (similarity(m.title || ' ' || m.content, :query) * 0.85) +
                        (COALESCE(m.importance, 0.5) * 0.15)
                    ) AS final_score
                FROM memories m
                WHERE m.status = 'active'
            """ + (t != null ? " AND m.type = :type " : "") + """
                  AND (
                      (similarity(m.title || ' ' || m.content, :query) > 0.03) OR
                      (:query = '')
                  )
                ORDER BY final_score DESC
                LIMIT :limit
            """;

            var spec = jdbcClient.sql(sql)
                    .param("query", q)
                    .param("limit", fetchLimit);
            if (t != null) {
                spec.param("type", t);
            }
            return spec.query((rs, rowNum) -> mapRow(rs)).list();
        }
    }

    private SearchHit mapRow(java.sql.ResultSet rs) throws java.sql.SQLException {
        MemoryDO mem = new MemoryDO();
        mem.setId(rs.getString("id"));
        mem.setType(rs.getString("type"));
        mem.setScope(rs.getString("scope"));
        mem.setTitle(rs.getString("title"));
        mem.setContent(rs.getString("content"));
        mem.setSource(rs.getString("source"));
        mem.setSourceAgent(rs.getString("source_agent"));
        mem.setProjectPath(rs.getString("project_path"));
        mem.setStatus(rs.getString("status"));
        mem.setDecayPolicy(rs.getString("decay_policy"));
        mem.setImportance(rs.getDouble("importance"));
        mem.setConfidence(rs.getDouble("confidence"));
        mem.setEffectivenessScore(rs.getDouble("effectiveness_score"));
        mem.setFeedbackScore(rs.getDouble("feedback_score"));
        mem.setInjectedCount(rs.getInt("injected_count"));
        mem.setIneffectiveCount(rs.getInt("ineffective_count"));
        mem.setSupersededBy(rs.getString("superseded_by"));
        mem.setFactLineageRoot(rs.getString("fact_lineage_root"));
        mem.setValidFrom(rs.getString("valid_from"));
        mem.setValidUntil(rs.getString("valid_until"));
        mem.setTags(readStringArray(rs, "tags"));
        mem.setRelatedIds(readStringArray(rs, "related_ids"));
        mem.setMetadata(readJsonMap(rs, "metadata"));

        Timestamp cAt = rs.getTimestamp("created_at");
        if (cAt != null) mem.setCreatedAt(cAt.toInstant());
        Timestamp uAt = rs.getTimestamp("updated_at");
        if (uAt != null) mem.setUpdatedAt(uAt.toInstant());
        Timestamp aAt = rs.getTimestamp("last_accessed_at");
        if (aAt != null) mem.setLastAccessedAt(aAt.toInstant());
        Timestamp iAt = rs.getTimestamp("last_injected_at");
        if (iAt != null) mem.setLastInjectedAt(iAt.toInstant());

        double vSim = rs.getDouble("vector_sim");
        double tSim = rs.getDouble("text_sim");
        double fScore = rs.getDouble("final_score");

        return new SearchHit(mem, fScore, vSim, tSim);
    }

    /**
     * 读取 PostgreSQL 原生 TEXT[] 数组列 (tags / related_ids)
     */
    private List<String> readStringArray(java.sql.ResultSet rs, String column) {
        try {
            java.sql.Array array = rs.getArray(column);
            if (array == null) {
                return new java.util.ArrayList<>();
            }
            Object raw = array.getArray();
            if (raw instanceof Object[] objects) {
                List<String> out = new java.util.ArrayList<>(objects.length);
                for (Object obj : objects) {
                    if (obj != null) {
                        out.add(String.valueOf(obj));
                    }
                }
                return out;
            }
            return new java.util.ArrayList<>();
        } catch (Exception e) {
            return new java.util.ArrayList<>();
        }
    }

    /**
     * 读取 PostgreSQL 原生 JSONB 列 (metadata)
     */
    private java.util.Map<String, Object> readJsonMap(java.sql.ResultSet rs, String column) {
        try {
            String raw = rs.getString(column);
            if (raw == null || raw.isBlank()) {
                return new java.util.HashMap<>();
            }
            return JSON_MAPPER.readValue(raw, new com.fasterxml.jackson.core.type.TypeReference<>() {});
        } catch (Exception e) {
            return new java.util.HashMap<>();
        }
    }

    private static final com.fasterxml.jackson.databind.ObjectMapper JSON_MAPPER =
            new com.fasterxml.jackson.databind.ObjectMapper();
}
