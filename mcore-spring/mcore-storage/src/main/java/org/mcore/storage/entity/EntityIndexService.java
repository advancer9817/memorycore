package org.mcore.storage.entity;

import org.mcore.common.model.MemoryDO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 记忆实体索引同步（对标 Python `entities.sync_memory_entities`）。
 *
 * 规则：
 * - 仅 `active` 记忆保留实体行；非 active 一律清空
 * - 先删后插（同一 memory_id 的实体集合整体替换）
 * - `(memory_id, normalized_entity)` 冲突时更新，保证幂等
 * - 兜底：即便正文未提及项目名，只要该记忆带可解析的 project_path/name，
 *   也补一条项目实体行，使 `entity_search("<project>")` 能确定性命中
 */
@Service
public class EntityIndexService {

    private static final Logger log = LoggerFactory.getLogger(EntityIndexService.class);

    private final JdbcClient jdbcClient;
    private final EntityExtractor extractor;
    private final org.mcore.storage.subject.SubjectContextService subjectContextService;

    public EntityIndexService(JdbcClient jdbcClient, EntityExtractor extractor,
                              org.mcore.storage.subject.SubjectContextService subjectContextService) {
        this.jdbcClient = jdbcClient;
        this.extractor = extractor;
        this.subjectContextService = subjectContextService;
    }

    /**
     * 同步一条记忆的实体索引。
     *
     * @return 写入的实体条数；非 active 或异常时为 0
     */
    public int sync(MemoryDO record) {
        if (record == null || record.getId() == null) {
            return 0;
        }
        String memoryId = record.getId();
        try {
            if (!"active".equals(record.getStatus())) {
                jdbcClient.sql("DELETE FROM memory_entities WHERE memory_id = :id")
                        .param("id", memoryId).update();
                return 0;
            }

            String text = (record.getTitle() == null ? "" : record.getTitle())
                    + "\n" + (record.getContent() == null ? "" : record.getContent());
            List<Map<String, Object>> entities = extractor.extractEntities(text, record.getTags());

            Map<String, Object> projectEntity = projectEntity(record);
            if (projectEntity != null) {
                final String pn = String.valueOf(projectEntity.get("normalized_entity"));
                boolean present = entities.stream()
                        .anyMatch(e -> pn.equals(String.valueOf(e.get("normalized_entity"))));
                if (!present) {
                    entities.add(projectEntity);
                    entities.sort((a, b) -> Double.compare(
                            ((Number) b.get("weight")).doubleValue(),
                            ((Number) a.get("weight")).doubleValue()));
                }
            }

            jdbcClient.sql("DELETE FROM memory_entities WHERE memory_id = :id")
                    .param("id", memoryId).update();

            int written = 0;
            for (Map<String, Object> e : entities) {
                String aliasesJson = toJsonArray((List<?>) e.get("aliases"));
                jdbcClient.sql(
                                "INSERT INTO memory_entities " +
                                "(id, memory_id, entity, normalized_entity, aliases_json, entity_type, weight, created_at) " +
                                "VALUES (:id, :memoryId, :entity, :normalized, CAST(:aliases AS jsonb), :type, :weight, clock_timestamp()) " +
                                "ON CONFLICT (memory_id, normalized_entity) DO UPDATE SET " +
                                "  entity = EXCLUDED.entity, " +
                                "  aliases_json = EXCLUDED.aliases_json, " +
                                "  entity_type = EXCLUDED.entity_type, " +
                                "  weight = EXCLUDED.weight")
                        .param("id", java.util.UUID.randomUUID().toString())
                        .param("memoryId", memoryId)
                        .param("entity", String.valueOf(e.get("entity")))
                        .param("normalized", String.valueOf(e.get("normalized_entity")))
                        .param("aliases", aliasesJson)
                        .param("type", String.valueOf(e.get("entity_type")))
                        .param("weight", ((Number) e.get("weight")).doubleValue())
                        .update();
                written++;
            }
            return written;
        } catch (Exception ex) {
            // 实体索引失败不应阻断记忆写入本身，但必须留痕（此前该类错误被静默吞掉）
            log.warn("实体索引同步失败: memory_id={} err={}", memoryId, ex.getMessage());
            return 0;
        }
    }

    /**
     * 由 project_path / project_name 派生项目实体。
     *
     * 说明：完整的项目解析（别名、discovery_roots 自动发现）属 `subject_context`
     * 能力，当前仍未移植；此处先保证"带项目归属的记忆必然进实体索引"这一
     * 确定性行为，避免实体索引继续停更。
     */
    private Map<String, Object> projectEntity(MemoryDO record) {
        // 优先走配置驱动的项目解析（别名、discovery_roots 自动发现）；
        // 解析不到时退回路径末段，保证"带项目路径的记忆必然进实体索引"。
        String name = null;
        try {
            Map<String, Object> proj = subjectContextService.resolveProject(
                    record.getProjectPath(), "");
            if (proj != null) {
                Object n = proj.get("name");
                if (n != null && !String.valueOf(n).isBlank()) {
                    name = String.valueOf(n);
                }
            }
        } catch (Exception e) {
            log.warn("项目实体解析失败，退回路径末段: {}", e.getMessage());
        }
        if (name == null) {
            String path = record.getProjectPath();
            if (path == null || path.isBlank()) {
                return null;
            }
            String trimmed = path.replaceAll("/+$", "");
            int idx = trimmed.lastIndexOf('/');
            name = idx >= 0 ? trimmed.substring(idx + 1) : trimmed;
        }
        if (name == null || name.isBlank()) {
            return null;
        }
        String normalized = EntityExtractor.canonicalEntity(name);
        if (normalized.isBlank()) {
            return null;
        }
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("entity", name);
        item.put("normalized_entity", normalized);
        item.put("aliases", EntityExtractor.aliasesOf(normalized));
        item.put("entity_type", "concept");
        item.put("weight", 1.0);
        return item;
    }

    private String toJsonArray(List<?> values) {
        StringBuilder sb = new StringBuilder("[");
        List<String> parts = new ArrayList<>();
        if (values != null) {
            for (Object v : values) {
                if (v == null) {
                    continue;
                }
                parts.add("\"" + String.valueOf(v).replace("\\", "\\\\").replace("\"", "\\\"") + "\"");
            }
        }
        sb.append(String.join(",", parts)).append("]");
        return sb.toString();
    }
}
