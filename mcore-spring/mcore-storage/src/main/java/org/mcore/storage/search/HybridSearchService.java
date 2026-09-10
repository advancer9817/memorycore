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
        float[] queryVec = embeddingService.embedText(query);
        return hybridSearch(query, queryVec, type, limit);
    }

    /**
     * 纯向量余弦距离检索 (供 memory_vector_search 工具使用)
     */
    public List<SearchHit> pureVectorSearch(String query, int limit) {
        float[] queryVec = embeddingService.embedText(query);
        PGvector vec = new PGvector(queryVec);
        int fetchLimit = limit > 0 ? limit : 10;

        String sql = """
            SELECT id, type, scope, title, content, source, source_agent, status,
                   importance, confidence, effectiveness_score, created_at, updated_at,
                   (1.0 - (embedding <=> :vec)) AS vector_sim,
                   0.0 AS text_sim,
                   (1.0 - (embedding <=> :vec)) AS final_score
            FROM memories
            WHERE status = 'active' AND embedding IS NOT NULL
            ORDER BY embedding <=> :vec ASC
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
                SELECT 
                    id, type, scope, title, content, source, source_agent, status,
                    importance, confidence, effectiveness_score, created_at, updated_at,
                    (CASE WHEN embedding IS NOT NULL THEN (1.0 - (embedding <=> :vec)) ELSE 0.0 END) AS vector_sim,
                    similarity(content, :query) AS text_sim,
                    (
                        (CASE WHEN embedding IS NOT NULL THEN (1.0 - (embedding <=> :vec)) * 0.65 ELSE 0.0 END) +
                        (similarity(content, :query) * (CASE WHEN embedding IS NOT NULL THEN 0.25 ELSE 0.85 END)) +
                        (COALESCE(importance, 0.5) * 0.10)
                    ) AS final_score
                FROM memories
                WHERE status = 'active'
            """ + (t != null ? " AND type = :type " : "") + """
                  AND (
                      (embedding IS NOT NULL AND (embedding <=> :vec) < 0.60) OR
                      (similarity(content, :query) > 0.08) OR
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
                SELECT 
                    id, type, scope, title, content, source, source_agent, status,
                    importance, confidence, effectiveness_score, created_at, updated_at,
                    0.0 AS vector_sim,
                    similarity(content, :query) AS text_sim,
                    (
                        (similarity(content, :query) * 0.85) +
                        (COALESCE(importance, 0.5) * 0.15)
                    ) AS final_score
                FROM memories
                WHERE status = 'active'
            """ + (t != null ? " AND type = :type " : "") + """
                  AND (
                      (similarity(content, :query) > 0.05) OR
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
        mem.setStatus(rs.getString("status"));
        mem.setImportance(rs.getDouble("importance"));
        mem.setConfidence(rs.getDouble("confidence"));
        mem.setEffectivenessScore(rs.getDouble("effectiveness_score"));
        Timestamp cAt = rs.getTimestamp("created_at");
        if (cAt != null) mem.setCreatedAt(cAt.toInstant());
        Timestamp uAt = rs.getTimestamp("updated_at");
        if (uAt != null) mem.setUpdatedAt(uAt.toInstant());

        double vSim = rs.getDouble("vector_sim");
        double tSim = rs.getDouble("text_sim");
        double fScore = rs.getDouble("final_score");

        return new SearchHit(mem, fScore, vSim, tSim);
    }
}
