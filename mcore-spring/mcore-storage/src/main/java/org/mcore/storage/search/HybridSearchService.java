package org.mcore.storage.search;

import com.pgvector.PGvector;
import org.mcore.common.model.MemoryDO;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.sql.Timestamp;
import java.util.List;

/**
 * 单阶段（Single-Pass）单 SQL 混合检索与联合加权打分服务
 */
@Service
public class HybridSearchService {

    private final JdbcClient jdbcClient;

    public record SearchHit(MemoryDO record, double finalScore, double vectorScore, double textScore) {}

    public HybridSearchService(JdbcClient jdbcClient) {
        this.jdbcClient = jdbcClient;
    }

    /**
     * 混合检索执行
     *
     * @param query     文本搜索词
     * @param embedding 向量数组 (可为 null)
     * @param type      记忆分类 (可选过滤)
     * @param limit     返回限制条数
     */
    public List<SearchHit> hybridSearch(String query, float[] embedding, String type, int limit) {
        PGvector vec = (embedding != null && embedding.length > 0) ? new PGvector(embedding) : null;
        boolean hasVector = (vec != null);
        int fetchLimit = limit > 0 ? limit : 10;
        String q = query != null ? query : "";
        String t = (type != null && !type.isBlank()) ? type.trim() : null;

        if (hasVector) {
            String sql = """
                SELECT 
                    id, type, scope, title, content, source, source_agent, status,
                    importance, confidence, effectiveness_score AS effectiveness, created_at, updated_at,
                    (1.0 - (embedding <=> :vec)) AS vector_sim,
                    similarity(content, :query) AS text_sim,
                    (
                        ((1.0 - (embedding <=> :vec)) * 0.65) +
                        (similarity(content, :query) * 0.25) +
                        (COALESCE(importance, 0.5) * 0.10)
                    ) AS final_score
                FROM memories
                WHERE status = 'active'
            """ + (t != null ? " AND type = :type " : "") + """
                  AND (
                      ((embedding <=> :vec) < 0.50) OR
                      (similarity(content, :query) > 0.10) OR
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
                    importance, confidence, effectiveness_score AS effectiveness, created_at, updated_at,
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
        mem.setEffectiveness(rs.getDouble("effectiveness"));
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
