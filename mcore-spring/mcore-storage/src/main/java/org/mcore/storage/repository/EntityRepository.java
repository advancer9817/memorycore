package org.mcore.storage.repository;

import org.mcore.storage.entity.EntityExtractor;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

import java.util.*;

/**
 * 实体检索（对标 Python `entities.entity_search`）。
 *
 * 修复前：裸 `LIKE '%query%'` 匹配 `normalized_entity` —— 丢弃别名归一
 * （查询 `memorycore` 匹配不到 `normalized_entity='mcore'` 的行），
 * 且无 active / 时效 / scope / project_path 过滤，排序也不含 importantce。
 */
@Repository
public class EntityRepository {

    private final JdbcClient jdbcClient;
    private final EntityExtractor extractor;

    public EntityRepository(JdbcClient jdbcClient, EntityExtractor extractor) {
        this.jdbcClient = jdbcClient;
        this.extractor = extractor;
    }

    public long count() {
        return jdbcClient.sql("SELECT count(*) FROM memory_entities").query(Long.class).single();
    }

    /** 索引新鲜度：最新实体行时间（用于暴露"索引停更"这一腐化信号） */
    public Map<String, Object> freshness() {
        return jdbcClient.sql(
                        "SELECT count(*) AS total, max(created_at) AS latest FROM memory_entities")
                .query().listOfRows().stream().findFirst().orElse(Map.of());
    }

    /**
     * 按实体检索记忆。
     *
     * @param query       查询文本（会被抽取为实体并归一）
     * @param limit       上限（1..100）
     * @param scope       记忆作用域过滤（空则不过滤）
     * @param projectPath 项目路径过滤（空则不过滤）
     */
    public List<Map<String, Object>> searchEntities(String query, int limit, String scope, String projectPath) {
        int cap = limit > 0 ? Math.min(limit, 100) : 20;

        List<Map<String, Object>> queryEntities = extractor.extractEntities(query, List.of());
        List<String> normalizedValues = new ArrayList<>();
        for (Map<String, Object> item : queryEntities) {
            String n = String.valueOf(item.get("normalized_entity"));
            if (!n.isBlank() && !"null".equals(n)) {
                normalizedValues.add(n);
            }
        }
        if (normalizedValues.isEmpty()) {
            String norm = EntityExtractor.canonicalEntity(query);
            if (!norm.isBlank()) {
                normalizedValues.add(norm);
            }
        }
        if (normalizedValues.isEmpty()) {
            return List.of();
        }

        // 统一走展开式查询：每个归一值一个独立占位符，单值与多值同一条代码路径
        return searchEntitiesExpanded(normalizedValues, cap, scope, projectPath);
    }

    /** 多实体展开查询（每个归一值一个独立占位符） */
    private List<Map<String, Object>> searchEntitiesExpanded(List<String> normalizedValues, int cap,
                                                             String scope, String projectPath) {
        List<String> ph = new ArrayList<>();
        for (int i = 0; i < normalizedValues.size(); i++) {
            ph.add(":p" + i);
        }
        StringBuilder sql = new StringBuilder(
                "SELECT m.id, m.title, m.content, m.type AS memory_type, m.scope AS memory_scope, " +
                "       m.importance, m.project_path, m.status, m.updated_at, " +
                "       e.entity AS matched_entity, e.normalized_entity AS matched_normalized_entity, " +
                "       e.entity_type AS matched_entity_type, e.weight AS matched_weight " +
                "FROM memory_entities e " +
                "JOIN memories m ON m.id = e.memory_id " +
                "WHERE e.normalized_entity IN (" + String.join(",", ph) + ") " +
                "  AND m.status = 'active' " +
                "  AND (m.valid_until IS NULL OR m.valid_until > now()) ");
        if (scope != null && !scope.isBlank()) {
            sql.append("  AND (m.scope = :scope OR m.scope = 'global') ");
        }
        if (projectPath != null && !projectPath.isBlank()) {
            sql.append("  AND (m.project_path = :project OR m.project_path = '' OR m.project_path IS NULL) ");
        }
        sql.append("ORDER BY e.weight DESC, m.importance DESC NULLS LAST, m.updated_at DESC LIMIT :limit");

        var spec = jdbcClient.sql(sql.toString());
        for (int i = 0; i < normalizedValues.size(); i++) {
            spec = spec.param("p" + i, normalizedValues.get(i));
        }
        if (scope != null && !scope.isBlank()) {
            spec = spec.param("scope", scope);
        }
        if (projectPath != null && !projectPath.isBlank()) {
            spec = spec.param("project", projectPath);
        }
        spec = spec.param("limit", cap);

        return decorate(spec.query().listOfRows(), normalizedValues);
    }

    /** 附加 boost 等派生字段（对标 Python：0.12 + min(weight,1.0)*0.18） */
    private List<Map<String, Object>> decorate(List<Map<String, Object>> rows, List<String> normalizedValues) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> row : rows) {
            Map<String, Object> m = new LinkedHashMap<>(row);
            double w = row.get("matched_weight") == null ? 0.0 : ((Number) row.get("matched_weight")).doubleValue();
            m.put("weight", w);
            m.put("memory_id", row.get("id"));
            m.put("boost", Math.round((0.12 + Math.min(w, 1.0) * 0.18) * 1000.0) / 1000.0);
            m.put("matched_query_entities", normalizedValues);
            out.add(m);
        }
        return out;
    }
}
