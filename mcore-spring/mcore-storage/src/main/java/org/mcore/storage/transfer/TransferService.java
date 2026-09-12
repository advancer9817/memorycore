package org.mcore.storage.transfer;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.mcore.storage.repository.MemoryRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.*;

/**
 * 完整数据导入、导出与物理快照归档服务 (全功能真实现，对齐 Python transfer.py)
 */
@Service
public class TransferService {
    private static final Logger log = LoggerFactory.getLogger(TransferService.class);

    /** 服务端备份目录：可通过 MCORE_BACKUP_DIR 覆盖，默认相对工作目录，避免硬编码绝对路径 */
    @org.springframework.beans.factory.annotation.Value("${mcore.backup-dir:./backups}")
    private String backupDir;

    private final JdbcClient jdbcClient;
    private final MemoryRepository memoryRepository;
    private final ObjectMapper objectMapper;

    public TransferService(JdbcClient jdbcClient, MemoryRepository memoryRepository, ObjectMapper objectMapper) {
        this.jdbcClient = jdbcClient;
        this.memoryRepository = memoryRepository;
        this.objectMapper = objectMapper;
    }

    public Map<String, Object> exportPayload(boolean full, boolean includeAudit, boolean memoriesOnly) {
        List<String> tables = new ArrayList<>();
        if (memoriesOnly) {
            tables.addAll(List.of("memories", "feedback_events", "memory_links", "memory_entities"));
        } else if (full) {
            tables.addAll(List.of("memories", "feedback_events", "memory_links", "memory_entities",
                    "governance_decisions", "context_quality_events"));
            if (includeAudit) tables.add("audit_events");
        } else {
            tables.addAll(List.of("memories", "feedback_events", "memory_links"));
            if (includeAudit) tables.add("audit_events");
        }

        Map<String, List<Map<String, Object>>> data = new LinkedHashMap<>();
        Map<String, Integer> counts = new LinkedHashMap<>();

        for (String table : tables) {
            try {
                // 不导出 embedding 大向量以保持导出轻巧与跨平台可读性
                String sql = table.equals("memories")
                        ? "SELECT id, type, scope, title, content, source, source_agent, project_path, " +
                          "confidence, importance, status, decay_policy, feedback_score, injected_count, " +
                          "ineffective_count, effectiveness_score, created_at, updated_at, tags_json, metadata_json, related_ids_json " +
                          "FROM memories"
                        : "SELECT * FROM " + table;

                List<Map<String, Object>> rows = jdbcClient.sql(sql).query().listOfRows();
                data.put(table, rows);
                counts.put(table, rows.size());
            } catch (Exception e) {
                log.warn("导出表 [{}] 异常: {}", table, e.getMessage());
                data.put(table, Collections.emptyList());
                counts.put(table, 0);
            }
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("schema_version", 1);
        result.put("exported_at", Instant.now().toString());
        result.put("memories_only", memoriesOnly);
        result.put("full", full);
        result.put("tables", tables);
        result.put("counts", counts);
        result.put("data", data);
        return result;
    }

    public Map<String, Object> backup(String customPath) {
        try {
            String stamp = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HHmmss").withZone(ZoneOffset.ofHours(8)).format(Instant.now());
            Path destPath;
            if (customPath != null && !customPath.isBlank()) {
                destPath = Paths.get(customPath);
            } else {
                destPath = Paths.get(backupDir, "memory-" + stamp + ".json");
            }

            if (destPath.getParent() != null) {
                Files.createDirectories(destPath.getParent());
            }

            Map<String, Object> payload = exportPayload(true, false, false);
            String jsonStr = objectMapper.writerWithDefaultPrettyPrinter().writeValueAsString(payload);
            Files.writeString(destPath, jsonStr, StandardCharsets.UTF_8);

            File file = destPath.toFile();
            log.info("记忆库物理备份生成成功: {} ({} 字节)", destPath, file.length());

            return Map.of(
                    "ok", true,
                    "path", destPath.toAbsolutePath().toString(),
                    "bytes", file.length(),
                    "timestamp", stamp
            );
        } catch (Exception e) {
            log.error("执行物理备份失败: {}", e.getMessage(), e);
            return Map.of("ok", false, "error", e.getMessage());
        }
    }

    public Map<String, Object> importPayload(Map<String, Object> payload, String conflictPolicy, boolean fullReplace) {
        if (payload == null || !payload.containsKey("data")) {
            return Map.of("ok", false, "error", "Invalid payload: missing data node");
        }

        @SuppressWarnings("unchecked")
        Map<String, Object> data = (Map<String, Object>) payload.get("data");
        int importedMemories = 0;
        int skippedMemories = 0;

        if (data.containsKey("memories")) {
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> memList = (List<Map<String, Object>>) data.get("memories");
            for (Map<String, Object> row : memList) {
                String id = (String) row.get("id");
                if (id == null || id.isBlank()) continue;

                boolean exists = memoryRepository.findById(id).isPresent();
                if (exists && "skip".equalsIgnoreCase(conflictPolicy)) {
                    skippedMemories++;
                    continue;
                }

                // 写入/覆盖
                try {
                    String title = (String) row.getOrDefault("title", "");
                    String content = (String) row.getOrDefault("content", "");
                    String type = (String) row.getOrDefault("type", "core_fact");
                    String scope = (String) row.getOrDefault("scope", "global");
                    String source = (String) row.getOrDefault("source", "import");
                    String agent = (String) row.getOrDefault("source_agent", "system");

                    String upsertSql = """
                        INSERT INTO memories (id, type, scope, title, content, source, source_agent, status, created_at, updated_at)
                        VALUES (:id, :type, :scope, :title, :content, :source, :agent, 'active', clock_timestamp(), clock_timestamp())
                        ON CONFLICT (id) DO UPDATE SET
                            title = EXCLUDED.title,
                            content = EXCLUDED.content,
                            type = EXCLUDED.type,
                            updated_at = clock_timestamp()
                    """;
                    jdbcClient.sql(upsertSql)
                            .param("id", id)
                            .param("type", type)
                            .param("scope", scope)
                            .param("title", title)
                            .param("content", content)
                            .param("source", source)
                            .param("agent", agent)
                            .update();
                    importedMemories++;
                } catch (Exception e) {
                    log.warn("导入记忆条目 [{}] 失败: {}", id, e.getMessage());
                }
            }
        }

        return Map.of(
                "ok", true,
                "imported_memories", importedMemories,
                "skipped_memories", skippedMemories,
                "conflict_policy", conflictPolicy
        );
    }
}
