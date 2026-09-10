package org.mcore.storage.repository;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.pgvector.PGvector;
import org.mcore.common.model.MemoryDO;
import org.mcore.storage.embedding.EmbeddingService;
import org.mcore.storage.mapper.MemoryMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Repository;

import java.util.*;

/**
 * 基于 MyBatis Mapper 的记忆持久化访问仓储
 */
@Repository
public class MemoryRepository {
    private static final Logger log = LoggerFactory.getLogger(MemoryRepository.class);

    private final MemoryMapper memoryMapper;
    private final EmbeddingService embeddingService;
    private final ObjectMapper objectMapper;

    public MemoryRepository(MemoryMapper memoryMapper, EmbeddingService embeddingService, ObjectMapper objectMapper) {
        this.memoryMapper = memoryMapper;
        this.embeddingService = embeddingService;
        this.objectMapper = objectMapper;
    }

    public long countActiveMemories() {
        return memoryMapper.countActive();
    }

    public long countTotalMemories() {
        return memoryMapper.countTotal();
    }

    public Map<String, Object> getDetailedStats() {
        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("total", countTotalMemories());
        stats.put("active", countActiveMemories());

        List<Map<String, Object>> byStatus = memoryMapper.countGroupedByStatus();
        Map<String, Long> statusMap = new LinkedHashMap<>();
        for (var row : byStatus) {
            String s = String.valueOf(row.get("status"));
            long c = ((Number) row.get("cnt")).longValue();
            statusMap.put(s, c);
        }
        stats.put("by_status", statusMap);
        return stats;
    }

    public Optional<MemoryDO> findById(String id) {
        return Optional.ofNullable(memoryMapper.selectById(id));
    }

    public List<MemoryDO> listRecent(int limit) {
        return memoryMapper.selectRecent(limit > 0 ? limit : 20);
    }

    public void insert(MemoryDO record) {
        if (record.getId() == null || record.getId().isBlank()) {
            record.setId(UUID.randomUUID().toString());
        }

        // 自动计算 768 维特征向量 (Ollama / OpenAI / 确定性伪哈希)
        float[] vec = record.getEmbedding();
        if (vec == null || vec.length == 0) {
            vec = embeddingService.embedText(record.getTitle() + " " + record.getContent());
            record.setEmbedding(vec);
        }

        memoryMapper.insert(record);
        if (vec != null && vec.length > 0) {
            memoryMapper.updateEmbedding(record.getId(), new PGvector(vec));
        }
    }

    public boolean update(String id, String content, String title, Double importance, String status) {
        MemoryDO record = new MemoryDO();
        record.setId(id);
        record.setTitle(title);
        record.setContent(content);
        record.setImportance(importance);
        record.setStatus(status);

        int rows = memoryMapper.update(record);
        if (content != null && !content.isBlank()) {
            float[] vec = embeddingService.embedText(content);
            memoryMapper.updateEmbedding(id, new PGvector(vec));
        }
        return rows > 0;
    }

    public boolean supersede(String oldId, MemoryDO newRecord) {
        insert(newRecord);
        MemoryDO old = new MemoryDO();
        old.setId(oldId);
        old.setStatus("superseded");
        old.setSupersededBy(newRecord.getId());
        return memoryMapper.update(old) > 0;
    }

    /**
     * 批量计算并补齐缺少向量的记忆 (全真向量索引回填)
     */
    public Map<String, Object> rebuildVectors(int limit) {
        int cap = limit > 0 ? Math.min(limit, 5000) : 1000;
        List<MemoryDO> unindexed = memoryMapper.selectNeedEmbedding(cap);
        log.info("发现 {} 条待回填向量的记忆记录", unindexed.size());

        int rebuilt = 0;
        for (var mem : unindexed) {
            String title = mem.getTitle() != null ? mem.getTitle() : "";
            String content = mem.getContent() != null ? mem.getContent() : "";
            float[] vec = embeddingService.embedText(title + " " + content);
            PGvector pgVec = new PGvector(vec);
            memoryMapper.updateEmbedding(mem.getId(), pgVec);
            rebuilt++;
        }
        return Map.of("rebuilt", rebuilt, "scanned", unindexed.size());
    }

    public List<Map<String, Object>> listWarnings() {
        return memoryMapper.selectWarnings();
    }

    public List<Map<String, Object>> listAuditLogs(int limit) {
        return memoryMapper.selectAuditLogs(limit > 0 ? limit : 30);
    }
}
