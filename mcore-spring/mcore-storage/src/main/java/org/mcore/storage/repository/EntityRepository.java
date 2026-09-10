package org.mcore.storage.repository;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

import java.util.*;

@Repository
public class EntityRepository {

    private final JdbcClient jdbcClient;

    public EntityRepository(JdbcClient jdbcClient) {
        this.jdbcClient = jdbcClient;
    }

    public long count() {
        return jdbcClient.sql("SELECT count(*) FROM memory_entities").query(Long.class).single();
    }

    public List<Map<String, Object>> searchEntities(String query, int limit) {
        int cap = limit > 0 ? Math.min(limit, 100) : 20;
        String q = (query != null ? query.trim().toLowerCase() : "");

        String sql = """
            SELECT e.id, e.entity, e.normalized_entity, e.entity_type, e.weight, e.memory_id,
                   m.title, m.content, m.type AS memory_type, m.scope AS memory_scope
            FROM memory_entities e
            JOIN memories m ON e.memory_id = m.id
            WHERE e.normalized_entity LIKE :pattern OR e.aliases_json::text LIKE :pattern
            ORDER BY e.weight DESC, e.created_at DESC
            LIMIT :limit
        """;

        return jdbcClient.sql(sql)
                .param("pattern", "%" + q + "%")
                .param("limit", cap)
                .query().listOfRows();
    }
}
