package org.mcore.storage.service;

import org.mcore.common.model.MemoryDO;
import org.mcore.storage.mapper.EntityMapper;
import org.mcore.storage.mapper.LinkMapper;
import org.mcore.storage.mapper.MemoryMapper;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.*;

@Service
public class MemoryQueryService {

    private final MemoryMapper memoryMapper;
    private final LinkMapper linkMapper;
    private final EntityMapper entityMapper;
    private final org.springframework.jdbc.core.simple.JdbcClient jdbcClient;

    public MemoryQueryService(MemoryMapper memoryMapper, LinkMapper linkMapper, EntityMapper entityMapper,
                              org.springframework.jdbc.core.simple.JdbcClient jdbcClient) {
        this.memoryMapper = memoryMapper;
        this.linkMapper = linkMapper;
        this.entityMapper = entityMapper;
        this.jdbcClient = jdbcClient;
    }

    private int parseInt(Object val, int defaultVal) {
        if (val == null) return defaultVal;
        if (val instanceof Number n) return n.intValue();
        try {
            return Integer.parseInt(String.valueOf(val).trim());
        } catch (Exception e) {
            return defaultVal;
        }
    }

    private double parseDouble(Object val, double defaultVal) {
        if (val == null) return defaultVal;
        if (val instanceof Number n) return n.doubleValue();
        try {
            return Double.parseDouble(String.valueOf(val).trim());
        } catch (Exception e) {
            return defaultVal;
        }
    }

    private boolean parseBoolean(Object val) {
        if (val == null) return false;
        if (val instanceof Boolean b) return b;
        return Boolean.parseBoolean(String.valueOf(val).trim());
    }

    private String formatIsoTimestamp(Object raw) {
        if (raw == null) return "";
        String str = String.valueOf(raw).trim();
        if (str.isEmpty()) return "";
        if (str.contains(" ") && !str.contains("T")) {
            str = str.replace(" ", "T");
        }
        if (!str.endsWith("Z") && !str.contains("+") && str.length() > 10) {
            str = str + "Z";
        }
        return str;
    }

    @SuppressWarnings("unchecked")
    private List<String> parseStringList(Object val) {
        if (val == null) return null;
        if (val instanceof List<?> l) {
            return l.stream().map(String::valueOf).toList();
        }
        String s = String.valueOf(val).trim();
        if (s.isEmpty()) return null;
        return Arrays.stream(s.split(",")).map(String::trim).filter(p -> !p.isEmpty()).toList();
    }

    public Map<String, Object> filterMemories(Map<String, Object> params) {
        if (params == null) params = Collections.emptyMap();

        int page = parseInt(params.get("page"), 1);
        int size = 20;
        if (params.get("size") != null) {
            size = parseInt(params.get("size"), 20);
        } else if (params.get("page_size") != null) {
            size = parseInt(params.get("page_size"), 20);
        } else if (params.get("limit") != null) {
            size = parseInt(params.get("limit"), 20);
        }
        page = Math.max(1, page);
        size = Math.max(1, Math.min(200, size));

        String searchQuery = params.get("search_query") != null ? String.valueOf(params.get("search_query")).trim() : "";
        if (searchQuery.isEmpty() && params.get("query") != null) {
            searchQuery = String.valueOf(params.get("query")).trim();
        }
        if (searchQuery.isEmpty() && params.get("search") != null) {
            searchQuery = String.valueOf(params.get("search")).trim();
        }

        String status = params.get("status") != null ? String.valueOf(params.get("status")).trim() : "";
        if ("all".equalsIgnoreCase(status)) {
            status = "";
        }
        boolean showArchived = parseBoolean(params.get("show_archived"));
        List<String> appIds = parseStringList(params.get("app_ids"));
        if (appIds == null && params.get("apps") != null) {
            appIds = parseStringList(params.get("apps"));
        }
        List<String> categoryIds = parseStringList(params.get("category_ids"));
        if (categoryIds == null && params.get("categories") != null) {
            categoryIds = parseStringList(params.get("categories"));
        }
        String sortColumn = params.get("sort_column") != null ? String.valueOf(params.get("sort_column")) : "created_at";
        if ("created_at".equals(sortColumn) && params.get("sort") != null) {
            sortColumn = String.valueOf(params.get("sort"));
        }
        String sortDir = "asc".equalsIgnoreCase(String.valueOf(params.get("sort_direction"))) || "asc".equalsIgnoreCase(String.valueOf(params.get("dir"))) ? "ASC" : "DESC";

        Map<String, Object> queryParams = new HashMap<>();
        queryParams.put("search_query", searchQuery);
        queryParams.put("status", status);
        queryParams.put("show_archived", showArchived);
        queryParams.put("app_ids", appIds);
        queryParams.put("category_ids", categoryIds);
        queryParams.put("sort_column", sortColumn);
        queryParams.put("sort_direction", sortDir);
        queryParams.put("limit", size);
        queryParams.put("offset", (page - 1) * size);

        // 1. 查询符合条件的总数 (MyBatis)
        long total = memoryMapper.countFilterMemories(queryParams);

        // 2. 查询当前分页记录 (MyBatis)
        List<Map<String, Object>> rows = memoryMapper.selectFilterMemories(queryParams);
        List<Map<String, Object>> items = new ArrayList<>();
        for (Map<String, Object> r : rows) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("id", r.get("id"));
            item.put("type", r.get("type"));
            item.put("scope", r.get("scope"));
            item.put("title", r.get("title"));
            item.put("content", r.get("content"));
            item.put("text", r.get("content"));
            item.put("source", r.get("source"));
            item.put("source_agent", r.get("source_agent"));
            item.put("app_id", r.get("source_agent"));
            item.put("app_name", r.get("source_agent"));
            item.put("status", r.get("status"));
            item.put("state", r.get("status"));
            item.put("importance", r.get("importance"));
            item.put("confidence", r.get("confidence"));
            item.put("effectiveness", r.get("effectiveness"));
            item.put("access_count", r.get("access_count"));
            item.put("categories", r.get("type") != null ? List.of(String.valueOf(r.get("type"))) : List.of());
            item.put("tags", r.get("type") != null ? List.of(String.valueOf(r.get("type"))) : List.of());
            item.put("metadata_", Map.of());
            item.put("superseded_by", "");
            item.put("created_at", formatIsoTimestamp(r.get("created_at")));
            item.put("updated_at", formatIsoTimestamp(r.get("updated_at")));
            items.add(item);
        }

        int pages = (int) Math.max(1, (total + size - 1) / size);
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("items", items);
        response.put("memories", items);
        response.put("total", total);
        response.put("page", page);
        response.put("size", size);
        response.put("page_size", size);
        response.put("pages", pages);
        return response;
    }

    public List<Map<String, Object>> getCategories() {
        return memoryMapper.selectCategories();
    }

    public Map<String, Object> getMemoryDetail(String id) {
        MemoryDO mem = memoryMapper.selectById(id);
        if (mem == null) {
            return null;
        }
        Map<String, Object> detail = new LinkedHashMap<>();
        detail.put("id", mem.getId());
        detail.put("type", mem.getType());
        detail.put("scope", mem.getScope());
        detail.put("title", mem.getTitle());
        detail.put("content", mem.getContent());
        detail.put("text", mem.getContent());
        detail.put("source", mem.getSource());
        detail.put("source_agent", mem.getSourceAgent());
        detail.put("status", mem.getStatus());
        detail.put("state", mem.getStatus());
        detail.put("importance", mem.getImportance());
        detail.put("confidence", mem.getConfidence());
        detail.put("effectiveness", mem.getEffectivenessScore());
        detail.put("access_count", mem.getInjectedCount());
        detail.put("created_at", String.valueOf(mem.getCreatedAt()));
        detail.put("updated_at", String.valueOf(mem.getUpdatedAt()));
        detail.put("categories", mem.getType() != null ? List.of(mem.getType()) : List.of());
        detail.put("app_name", mem.getSourceAgent());
        detail.put("metadata_", Map.of());

        // 查询实体 (MyBatis)
        detail.put("entities", entityMapper.selectByMemoryId(id));

        // 查询关联 (MyBatis)
        detail.put("links", linkMapper.selectLinksBySourceId(id));
        return detail;
    }

    public boolean updateMemory(String id, String title, String content, Double importance, String status) {
        MemoryDO mem = new MemoryDO();
        mem.setId(id);
        mem.setTitle(title);
        mem.setContent(content);
        mem.setImportance(importance);
        mem.setStatus(status);
        return memoryMapper.update(mem) > 0;
    }

    public boolean batchUpdateStatus(List<String> ids, String status) {
        if (ids == null || ids.isEmpty()) return true;
        return memoryMapper.batchUpdateStatus(ids, status) > 0;
    }

    public Map<String, Object> createMemory(Map<String, Object> body) {
        if (body == null) body = Collections.emptyMap();
        String id = "mem_" + UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        String type = String.valueOf(body.getOrDefault("type", "project_memory"));
        String title = String.valueOf(body.getOrDefault("title", ""));
        String content = body.get("content") != null ? String.valueOf(body.get("content")) : String.valueOf(body.getOrDefault("text", ""));
        if (title.isBlank() && !content.isBlank()) {
            String firstLine = content.lines().findFirst().orElse("Memory");
            title = firstLine.substring(0, Math.min(80, firstLine.length()));
        }
        String scope = String.valueOf(body.getOrDefault("scope", "global"));
        String source = String.valueOf(body.getOrDefault("source", "manual"));
        String sourceAgent = String.valueOf(body.getOrDefault("source_agent", body.getOrDefault("agent", "ui")));
        String projectPath = body.get("project_path") != null ? String.valueOf(body.get("project_path")) : "";
        double importance = parseDouble(body.get("importance"), 0.5);
        double confidence = parseDouble(body.get("confidence"), 0.7);
        String status = String.valueOf(body.getOrDefault("status", "active"));

        MemoryDO record = new MemoryDO();
        record.setId(id);
        record.setType(type);
        record.setScope(scope);
        record.setTitle(title);
        record.setContent(content);
        record.setSource(source);
        record.setSourceAgent(sourceAgent);
        record.setProjectPath(projectPath);
        record.setImportance(importance);
        record.setConfidence(confidence);
        record.setStatus(status);
        record.setDecayPolicy("review");
        record.setFeedbackScore(0.0);
        record.setInjectedCount(0);
        record.setIneffectiveCount(0);
        record.setEffectivenessScore(0.5);
        record.setTags(parseStringList(body.get("tags")));

        Object metadata = body.get("metadata");
        if (metadata instanceof Map<?, ?> metaMap) {
            Map<String, Object> normalized = new LinkedHashMap<>();
            metaMap.forEach((k, v) -> normalized.put(String.valueOf(k), v));
            record.setMetadata(normalized);
        }

        memoryMapper.insert(record);

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("id", id);
        res.put("title", title);
        res.put("content", content);
        res.put("type", type);
        res.put("tags", record.getTags());
        res.put("status", status);
        res.put("state", status);
        res.put("app_name", sourceAgent);
        res.put("categories", List.of(type));
        return res;
    }

    public Map<String, Object> getRelatedMemories(String memoryId) {
        List<Map<String, Object>> rows = linkMapper.selectRelatedMemories(memoryId, 50);
        List<Map<String, Object>> items = new ArrayList<>();
        for (Map<String, Object> r : rows) {
            Map<String, Object> item = new LinkedHashMap<>(r);
            item.put("state", r.get("status"));
            item.put("categories", r.get("type") != null ? List.of(String.valueOf(r.get("type"))) : List.of());
            item.put("app_name", r.get("source_agent"));
            items.add(item);
        }
        return Map.of("items", items, "total", items.size(), "page", 1, "size", items.size(), "pages", 1);
    }

    /**
     * 记忆访问日志。
     *
     * 修复要点：原实现忽略分页参数，并把 updated_at 冒充 accessed_at **凭空造出一条日志**，
     * 而表内真实存在的 injected_count / last_accessed_at / last_injected_at 三列完全未被使用。
     *
     * 现实现：
     * - logs   ← audit_events 中该记忆的真实离散事件（分页）
     * - summary ← memories 上的真实聚合访问元数据
     */
    public Map<String, Object> getAccessLogs(String memoryId, int page, int pageSize) {
        int p = Math.max(1, page);
        int size = Math.max(1, Math.min(pageSize, 100));
        int offset = (p - 1) * size;

        Long total = jdbcClient.sql("SELECT COUNT(*) FROM audit_events WHERE memory_id = :id")
                .param("id", memoryId).query(Long.class).single();

        List<Map<String, Object>> logs = org.mcore.storage.util.JsonbRows.rows(
                jdbcClient.sql("SELECT id, event_type, agent, detail_json, created_at " +
                                "FROM audit_events WHERE memory_id = :id " +
                                "ORDER BY created_at DESC NULLS LAST LIMIT :limit OFFSET :offset")
                        .param("id", memoryId).param("limit", size).param("offset", offset)
                        .query().listOfRows());

        List<Map<String, Object>> normalized = new ArrayList<>();
        for (Map<String, Object> row : logs) {
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("id", row.get("id"));
            entry.put("app_name", row.get("agent") != null ? row.get("agent") : "unknown");
            entry.put("event_type", row.get("event_type"));
            entry.put("accessed_at", row.get("created_at"));
            entry.put("detail", row.get("detail_json"));
            normalized.add(entry);
        }

        // 真实聚合访问元数据（此前完全未暴露）
        Map<String, Object> summary = new LinkedHashMap<>();
        Map<String, Object> memRow = jdbcClient.sql(
                        "SELECT injected_count, last_accessed_at, last_injected_at FROM memories WHERE id = :id")
                .param("id", memoryId).query().listOfRows().stream().findFirst().orElse(null);
        if (memRow != null) {
            summary.put("injected_count", memRow.get("injected_count"));
            summary.put("last_accessed_at", memRow.get("last_accessed_at"));
            summary.put("last_injected_at", memRow.get("last_injected_at"));
        }

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("total", total);
        res.put("page", p);
        res.put("page_size", size);
        res.put("logs", normalized);
        res.put("summary", summary);
        return res;
    }

    /** 兼容旧签名 */
    public Map<String, Object> getAccessLogs(String memoryId) {
        return getAccessLogs(memoryId, 1, 10);
    }

    /**
     * 「被访问过的记忆」列表。
     *
     * 修复要点：此前 apps/{id}/accessed 直接复用 filterMemories，返回的是该 app 的**全部**记忆，
     * 与"访问过"这一语义无关。现按真实访问时间排序，并过滤掉从未被访问的记录。
     */
    public Map<String, Object> listAccessedMemories(List<String> appIds, int page, int pageSize) {
        int p = Math.max(1, page);
        int size = Math.max(1, Math.min(pageSize, 200));
        int offset = (p - 1) * size;
        List<String> ids = (appIds == null || appIds.isEmpty()) ? List.of("") : appIds;

        StringBuilder ph = new StringBuilder();
        Map<String, Object> params = new LinkedHashMap<>();
        for (int i = 0; i < ids.size(); i++) {
            if (i > 0) ph.append(",");
            ph.append(":sid").append(i);
            params.put("sid" + i, ids.get(i));
        }

        String where = " WHERE source_agent IN (" + ph + ") AND last_accessed_at IS NOT NULL";
        Long total = jdbcClient.sql("SELECT COUNT(*) FROM memories" + where)
                .params(params).query(Long.class).single();

        Map<String, Object> qp = new LinkedHashMap<>(params);
        qp.put("limit", size);
        qp.put("offset", offset);
        List<Map<String, Object>> items = org.mcore.storage.util.JsonbRows.rows(jdbcClient.sql(
                        "SELECT id, title, source_agent, status, importance, injected_count, " +
                                "last_accessed_at, last_injected_at, created_at FROM memories" + where +
                                " ORDER BY last_accessed_at DESC LIMIT :limit OFFSET :offset")
                .params(qp).query().listOfRows());

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("items", items);
        res.put("total", total);
        res.put("page", p);
        res.put("page_size", size);
        return res;
    }

    public Map<String, Object> getLineage(String memoryId) {
        List<Map<String, Object>> links = linkMapper.selectLineageLinks(memoryId);
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("memory_id", memoryId);
        res.put("links", links);
        return res;
    }
}
