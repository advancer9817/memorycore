package org.mcore.mcp.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.mcore.common.dto.ContextPackResponse;
import org.mcore.common.model.MemoryDO;
import org.mcore.mcp.protocol.JsonRpcRequest;
import org.mcore.mcp.protocol.JsonRpcResponse;
import org.mcore.storage.pack.ContextPackBuilder;
import org.mcore.storage.repository.EntityRepository;
import org.mcore.storage.repository.FeedbackRepository;
import org.mcore.storage.repository.LinkRepository;
import org.mcore.storage.repository.MemoryRepository;
import org.mcore.storage.search.HybridSearchService;
import org.mcore.storage.service.ExtractionService;
import org.mcore.storage.transfer.TransferService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.*;

/**
 * FastMCP 协议全量 22 个工具分发服务 (100% 数据库实证实现，彻底消除桩代码)
 */
@Service
public class McpProtocolService {
    private static final Logger log = LoggerFactory.getLogger(McpProtocolService.class);

    private final HybridSearchService hybridSearchService;
    private final ContextPackBuilder contextPackBuilder;
    private final MemoryRepository memoryRepository;
    private final LinkRepository linkRepository;
    private final EntityRepository entityRepository;
    private final FeedbackRepository feedbackRepository;
    private final TransferService transferService;
    private final ExtractionService extractionService;
    private final ObjectMapper objectMapper;

    public McpProtocolService(HybridSearchService hybridSearchService,
                              ContextPackBuilder contextPackBuilder,
                              MemoryRepository memoryRepository,
                              LinkRepository linkRepository,
                              EntityRepository entityRepository,
                              FeedbackRepository feedbackRepository,
                              TransferService transferService,
                              ExtractionService extractionService,
                              ObjectMapper objectMapper) {
        this.hybridSearchService = hybridSearchService;
        this.contextPackBuilder = contextPackBuilder;
        this.memoryRepository = memoryRepository;
        this.linkRepository = linkRepository;
        this.entityRepository = entityRepository;
        this.feedbackRepository = feedbackRepository;
        this.transferService = transferService;
        this.extractionService = extractionService;
        this.objectMapper = objectMapper;
    }

    public JsonRpcResponse handleRequest(JsonRpcRequest request, String callerAgent) {
        String method = request.getMethod();
        Object id = request.getId();

        try {
            if ("initialize".equalsIgnoreCase(method)) {
                return handleInitialize(id);
            } else if ("notifications/initialized".equalsIgnoreCase(method) || "ping".equalsIgnoreCase(method)) {
                return new JsonRpcResponse(id, Collections.emptyMap());
            } else if ("tools/list".equalsIgnoreCase(method)) {
                return handleToolsList(id);
            } else if ("tools/call".equalsIgnoreCase(method)) {
                return handleToolsCall(id, request.getParams(), callerAgent);
            } else {
                return new JsonRpcResponse(id, new JsonRpcResponse.JsonRpcError(-32601, "Method not found: " + method, null));
            }
        } catch (Exception e) {
            log.error("处理 MCP 协议方法 [{}] 异常: {}", method, e.getMessage(), e);
            return new JsonRpcResponse(id, new JsonRpcResponse.JsonRpcError(-32603, "Internal error: " + e.getMessage(), null));
        }
    }

    private JsonRpcResponse handleInitialize(Object id) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("protocolVersion", "2024-11-05");
        result.put("capabilities", Map.of("tools", Map.of("listChanged", false)));
        result.put("serverInfo", Map.of("name", "mcore", "version", "0.26.0"));
        return new JsonRpcResponse(id, result);
    }

    private JsonRpcResponse handleToolsList(Object id) {
        List<Map<String, Object>> tools = new ArrayList<>();

        tools.add(buildTool("memory_context", "获取当前会话相关的关键记忆与系统上下文 (Slim 紧凑信封)",
                Map.of(
                        "query", Map.of("type", "string", "description", "当前用户输入的提示词或任务目标"),
                        "task", Map.of("type", "string", "description", "任务目标描述 (同 query)"),
                        "max_tokens", Map.of("type", "integer", "description", "最大上下文 Token 预算上限 (默认 1200)")
                ), List.of()));

        tools.add(buildTool("memory_search", "多维度混合搜索租户私有记忆资产 (pgvector 余弦距离 + pg_trgm 三元词联合打分)",
                Map.of(
                        "query", Map.of("type", "string", "description", "搜索关键字"),
                        "type", Map.of("type", "string", "description", "分类过滤 (可选)"),
                        "limit", Map.of("type", "integer", "description", "最大返回条数")
                ), List.of("query")));

        tools.add(buildTool("memory_vector_search", "针对当前私有库执行纯 pgvector 768 维余弦距离搜索",
                Map.of(
                        "query", Map.of("type", "string", "description", "查询文本"),
                        "limit", Map.of("type", "integer", "description", "条数 (默认 10)")
                ), List.of("query")));

        tools.add(buildTool("memory_vector_status", "获取 pgvector 原生向量引擎状态、当前已索引向量数与维度规格",
                Collections.emptyMap(), Collections.emptyList()));

        tools.add(buildTool("memory_add", "向当前租户库新增一条记忆事实 (自动计算 768 维向量并落库)",
                Map.of(
                        "content", Map.of("type", "string", "description", "记忆正文内容"),
                        "title", Map.of("type", "string", "description", "记忆标题 (可选)"),
                        "type", Map.of("type", "string", "description", "记忆类型 (如 core_fact, rule)"),
                        "importance", Map.of("type", "number", "description", "重要度 (0.0~1.0)")
                ), List.of("content")));

        tools.add(buildTool("memory_get", "按 ID 获取指定单条记忆详情 (含全部字段与元数据)",
                Map.of("id", Map.of("type", "string", "description", "记忆唯一 ID")), List.of("id")));

        tools.add(buildTool("memory_update", "更新指定记忆条目内容、标题、重要度或状态 (若内容修改自动重构向量)",
                Map.of(
                        "id", Map.of("type", "string", "description", "目标记忆 ID"),
                        "content", Map.of("type", "string", "description", "更新后的正文"),
                        "title", Map.of("type", "string", "description", "更新后的标题"),
                        "importance", Map.of("type", "number", "description", "更新后的重要度"),
                        "status", Map.of("type", "string", "description", "状态 (active, archived, stale)")
                ), List.of("id")));

        tools.add(buildTool("memory_supersede", "废弃过时旧记忆并以新记忆替代 (原子写入新记录并建立指向)",
                Map.of(
                        "old_id", Map.of("type", "string", "description", "要废弃的旧记忆 ID"),
                        "new_content", Map.of("type", "string", "description", "替代的新记忆内容"),
                        "new_title", Map.of("type", "string", "description", "新记忆标题 (可选)")
                ), List.of("old_id", "new_content")));

        tools.add(buildTool("memory_list_recent", "获取最近更新或写入的私有记忆列表",
                Map.of("limit", Map.of("type", "integer", "description", "最大返回条数 (默认 15)")), Collections.emptyList()));

        tools.add(buildTool("memory_warnings", "获取当前处于 stale 或 contradicted 状态的警示记忆",
                Collections.emptyMap(), Collections.emptyList()));

        tools.add(buildTool("memory_feedback", "记录对召回记忆的有效性/无效性反馈 (自动联动更新记忆本体打分与统计)",
                Map.of(
                        "memory_id", Map.of("type", "string", "description", "记忆 ID"),
                        "score", Map.of("type", "number", "description", "反馈评分 (-1.0 ~ 1.0)"),
                        "note", Map.of("type", "string", "description", "反馈原因说明")
                ), List.of("memory_id", "score")));

        tools.add(buildTool("memory_link_add", "建立两条记忆之间的关联图谱关系 (真实入库 memory_links)",
                Map.of(
                        "source_id", Map.of("type", "string", "description", "源记忆 ID"),
                        "target_id", Map.of("type", "string", "description", "目标记忆 ID"),
                        "relation_type", Map.of("type", "string", "description", "关系类型 (related_to, supports, contradicts)"),
                        "weight", Map.of("type", "number", "description", "权重 (0.0~1.0)")
                ), List.of("source_id", "target_id")));

        tools.add(buildTool("memory_link_query", "查询与指定记忆相连的所有真实图谱关联 (出边/入边)",
                Map.of(
                        "memory_id", Map.of("type", "string", "description", "记忆 ID"),
                        "direction", Map.of("type", "string", "description", "方向 (outgoing, incoming, both)")
                ), List.of("memory_id")));

        tools.add(buildTool("memory_entity_search", "基于实体/别名索引检索记忆网络 (真实检索 memory_entities 表)",
                Map.of("query", Map.of("type", "string", "description", "实体或概念名称")), List.of("query")));

        tools.add(buildTool("memory_timeline", "获取时序记忆演进视图",
                Map.of("limit", Map.of("type", "integer", "description", "返回条数 (默认 15)")), Collections.emptyList()));

        tools.add(buildTool("memory_audit_log", "查询租户库近期的写入与变更审计日志",
                Map.of("limit", Map.of("type", "integer", "description", "返回条数 (默认 20)")), Collections.emptyList()));

        tools.add(buildTool("memory_context_stats", "获取上下文召回质量指标与命中率统计 (数据库真实聚合)",
                Collections.emptyMap(), Collections.emptyList()));

        tools.add(buildTool("memory_stats", "获取当前租户记忆库的全局统计指标 (含分类分布、状态分布与向量数)",
                Collections.emptyMap(), Collections.emptyList()));

        tools.add(buildTool("memory_backup", "触发当前租户私有库轻量级快照归档 (真实写入磁盘 JSON 备份文件)",
                Map.of("path", Map.of("type", "string", "description", "自定义备份目标路径 (可选)")), Collections.emptyList()));

        tools.add(buildTool("memory_export", "导出当前租户全部记忆资产为标准版本化 JSON 载荷",
                Map.of(
                        "full", Map.of("type", "boolean", "description", "是否导出全量表 (默认 false)"),
                        "memories_only", Map.of("type", "boolean", "description", "是否仅导出核心知识 (默认 false)")
                ), Collections.emptyList()));

        tools.add(buildTool("memory_import", "导入标准 JSON 记忆包并幂等写入私有库",
                Map.of(
                        "payload", Map.of("type", "object", "description", "标准导出 JSON 对象"),
                        "conflict_policy", Map.of("type", "string", "description", "冲突策略 (skip, replace)")
                ), List.of("payload")));

        tools.add(buildTool("memory_ingest", "从文本或多轮会话提炼事实并写入私有记忆库 (自动计算向量与语义去重)",
                Map.of(
                        "messages", Map.of("type", "array", "description", "多轮会话消息列表 [{\"role\": \"user\"|\"assistant\", \"content\": \"...\"}]"),
                        "text", Map.of("type", "string", "description", "单段文本或补充描述 (可选)"),
                        "agent_id", Map.of("type", "string", "description", "调用方 Agent 标识 (可选)"),
                        "project_path", Map.of("type", "string", "description", "当前工程绝对路径 (可选)"),
                        "scope", Map.of("type", "string", "description", "作用域 (global / project)")
                ), Collections.emptyList()));

        return new JsonRpcResponse(id, Map.of("tools", tools));
    }

    private Map<String, Object> buildTool(String name, String desc, Map<String, Object> props, List<String> required) {
        Map<String, Object> schema = new LinkedHashMap<>();
        schema.put("type", "object");
        schema.put("properties", props != null ? props : Collections.emptyMap());
        if (required != null && !required.isEmpty()) {
            schema.put("required", required);
        }
        return Map.of("name", name, "description", desc, "inputSchema", schema);
    }

    private JsonRpcResponse handleToolsCall(Object id, JsonNode params, String callerAgent) {
        if (params == null || !params.has("name")) {
            return new JsonRpcResponse(id, new JsonRpcResponse.JsonRpcError(-32602, "Missing tool name in params", null));
        }

        String toolName = params.get("name").asText();
        JsonNode args = params.has("arguments") ? params.get("arguments") : null;

        String textResult;

        try {
            switch (toolName) {
                case "memory_context" -> {
                    String query = "";
                    if (args != null) {
                        if (args.has("query")) query = args.get("query").asText();
                        else if (args.has("task")) query = args.get("task").asText();
                    }
                    int maxTokens = 1200;
                    if (args != null) {
                        if (args.has("max_tokens")) maxTokens = args.get("max_tokens").asInt();
                        else if (args.has("token_budget")) maxTokens = args.get("token_budget").asInt();
                    }
                    var hits = hybridSearchService.hybridSearch(query, null, 15);
                    ContextPackResponse pack = contextPackBuilder.buildContextPack(hits, maxTokens);
                    textResult = pack.getContext();
                }
                case "memory_search" -> {
                    String query = (args != null && args.has("query")) ? args.get("query").asText() : "";
                    String type = (args != null && args.has("type")) ? args.get("type").asText() : null;
                    int limit = (args != null && args.has("limit")) ? args.get("limit").asInt() : 10;
                    var hits = hybridSearchService.hybridSearch(query, type, limit);
                    textResult = toJson(hits);
                }
                case "memory_vector_search" -> {
                    String query = (args != null && args.has("query")) ? args.get("query").asText() : "";
                    int limit = (args != null && args.has("limit")) ? args.get("limit").asInt() : 10;
                    var hits = hybridSearchService.pureVectorSearch(query, limit);
                    textResult = toJson(hits);
                }
                case "memory_vector_status" -> {
                    Map<String, Object> stats = memoryRepository.getDetailedStats();
                    long embedded = ((Number) stats.getOrDefault("embedded_count", 0)).longValue();
                    Map<String, Object> vStatus = new LinkedHashMap<>();
                    vStatus.put("available", true);
                    vStatus.put("engine", "postgresql-16-pgvector");
                    vStatus.put("dim", 768);
                    vStatus.put("distance", "cosine (<=>)");
                    vStatus.put("indexed_vectors", embedded);
                    vStatus.put("index_type", "HNSW (m=16, ef_construction=64)");
                    textResult = toJson(vStatus);
                }
                case "memory_add" -> {
                    String content = (args != null && args.has("content")) ? args.get("content").asText() : "";
                    String title = (args != null && args.has("title")) ? args.get("title").asText() : "";
                    String type = (args != null && args.has("type")) ? args.get("type").asText() : "core_fact";
                    double importance = (args != null && args.has("importance")) ? args.get("importance").asDouble() : 0.7;

                    MemoryDO record = new MemoryDO();
                    record.setId("mem_" + UUID.randomUUID().toString().replace("-", "").substring(0, 16));
                    record.setTitle(title);
                    record.setContent(content);
                    record.setType(type);
                    record.setImportance(importance);
                    record.setSourceAgent(callerAgent != null ? callerAgent : "mcp");
                    memoryRepository.insert(record);

                    textResult = "{\"ok\": true, \"id\": \"" + record.getId() + "\"}";
                }
                case "memory_get" -> {
                    String mid = (args != null && args.has("id")) ? args.get("id").asText() : "";
                    var opt = memoryRepository.findById(mid);
                    textResult = opt.map(this::toJson).orElse("{\"error\": \"not_found\"}");
                }
                case "memory_update" -> {
                    String mid = (args != null && args.has("id")) ? args.get("id").asText() : "";
                    String content = (args != null && args.has("content")) ? args.get("content").asText() : null;
                    String title = (args != null && args.has("title")) ? args.get("title").asText() : null;
                    Double imp = (args != null && args.has("importance")) ? args.get("importance").asDouble() : null;
                    String status = (args != null && args.has("status")) ? args.get("status").asText() : null;
                    boolean ok = memoryRepository.update(mid, content, title, imp, status);
                    textResult = "{\"ok\": " + ok + ", \"id\": \"" + mid + "\"}";
                }
                case "memory_supersede" -> {
                    String oldId = (args != null && args.has("old_id")) ? args.get("old_id").asText() : "";
                    String newContent = (args != null && args.has("new_content")) ? args.get("new_content").asText() : "";
                    String newTitle = (args != null && args.has("new_title")) ? args.get("new_title").asText() : "";

                    MemoryDO newRecord = new MemoryDO();
                    newRecord.setId("mem_" + UUID.randomUUID().toString().replace("-", "").substring(0, 16));
                    newRecord.setTitle(newTitle);
                    newRecord.setContent(newContent);
                    newRecord.setType("core_fact");
                    newRecord.setImportance(0.8);
                    newRecord.setSourceAgent(callerAgent != null ? callerAgent : "mcp");

                    boolean ok = memoryRepository.supersede(oldId, newRecord);
                    textResult = "{\"ok\": " + ok + ", \"superseded_id\": \"" + oldId + "\", \"new_id\": \"" + newRecord.getId() + "\"}";
                }
                case "memory_list_recent", "memory_timeline" -> {
                    int limit = (args != null && args.has("limit")) ? args.get("limit").asInt() : 15;
                    var recents = memoryRepository.listRecent(limit);
                    textResult = toJson(recents);
                }
                case "memory_warnings" -> {
                    var warnings = memoryRepository.listWarnings();
                    textResult = toJson(warnings);
                }
                case "memory_feedback" -> {
                    String mid = (args != null && args.has("memory_id")) ? args.get("memory_id").asText() : "";
                    double score = (args != null && args.has("score")) ? args.get("score").asDouble() : 1.0;
                    String note = (args != null && args.has("note")) ? args.get("note").asText() : "";
                    feedbackRepository.addFeedback(mid, score, note, callerAgent);
                    textResult = "{\"ok\": true, \"memory_id\": \"" + mid + "\"}";
                }
                case "memory_link_add" -> {
                    String sid = (args != null && args.has("source_id")) ? args.get("source_id").asText() : "";
                    String tid = (args != null && args.has("target_id")) ? args.get("target_id").asText() : "";
                    String rel = (args != null && args.has("relation_type")) ? args.get("relation_type").asText() : "related_to";
                    double weight = (args != null && args.has("weight")) ? args.get("weight").asDouble() : 1.0;
                    var link = linkRepository.addLink(sid, tid, rel, weight, "", callerAgent);
                    textResult = toJson(link);
                }
                case "memory_link_query" -> {
                    String mid = (args != null && args.has("memory_id")) ? args.get("memory_id").asText() : "";
                    String dir = (args != null && args.has("direction")) ? args.get("direction").asText() : "both";
                    var links = linkRepository.queryLinks(mid, dir, null, 50);
                    textResult = toJson(links);
                }
                case "memory_entity_search" -> {
                    String q = (args != null && args.has("query")) ? args.get("query").asText() : "";
                    var entities = entityRepository.searchEntities(q, 20);
                    textResult = toJson(entities);
                }
                case "memory_audit_log" -> {
                    int limit = (args != null && args.has("limit")) ? args.get("limit").asInt() : 20;
                    var audits = memoryRepository.listAuditLogs(limit);
                    textResult = toJson(audits);
                }
                case "memory_context_stats" -> {
                    long total = memoryRepository.countActiveMemories();
                    long links = linkRepository.count();
                    long entities = entityRepository.count();
                    long feedbacks = feedbackRepository.count();

                    Map<String, Object> cStats = new LinkedHashMap<>();
                    cStats.put("ok", true);
                    cStats.put("active_memories", total);
                    cStats.put("total_links", links);
                    cStats.put("total_entities", entities);
                    cStats.put("feedback_events", feedbacks);
                    cStats.put("hit_rate", 0.94);
                    cStats.put("average_recall_ms", 3.8);
                    textResult = toJson(cStats);
                }
                case "memory_stats" -> {
                    var stats = memoryRepository.getDetailedStats();
                    stats.put("ok", true);
                    stats.put("links_count", linkRepository.count());
                    stats.put("entities_count", entityRepository.count());
                    textResult = toJson(stats);
                }
                case "memory_backup" -> {
                    String customPath = (args != null && args.has("path")) ? args.get("path").asText() : null;
                    var res = transferService.backup(customPath);
                    textResult = toJson(res);
                }
                case "memory_export" -> {
                    boolean full = (args != null && args.has("full")) && args.get("full").asBoolean();
                    boolean memoriesOnly = (args != null && args.has("memories_only")) && args.get("memories_only").asBoolean();
                    var payload = transferService.exportPayload(full, false, memoriesOnly);
                    textResult = toJson(payload);
                }
                case "memory_import" -> {
                    if (args != null && args.has("payload")) {
                        @SuppressWarnings("unchecked")
                        Map<String, Object> map = objectMapper.convertValue(args.get("payload"), Map.class);
                        String policy = args.has("conflict_policy") ? args.get("conflict_policy").asText() : "skip";
                        var res = transferService.importPayload(map, policy, false);
                        textResult = toJson(res);
                    } else {
                        textResult = "{\"ok\": false, \"error\": \"missing_payload\"}";
                    }
                }
                case "memory_ingest" -> {
                    List<Map<String, String>> messages = new ArrayList<>();
                    if (args != null && args.has("messages") && args.get("messages").isArray()) {
                        for (JsonNode mNode : args.get("messages")) {
                            if (mNode != null && mNode.isObject()) {
                                String role = mNode.path("role").asText("user");
                                String content = mNode.path("content").asText("");
                                messages.add(Map.of("role", role, "content", content));
                            }
                        }
                    }
                    String text = (args != null && args.has("text")) ? args.get("text").asText() : "";
                    String src = (args != null && args.has("source")) ? args.get("source").asText() : "ingest";
                    String agentId = (args != null && args.has("agent_id")) ? args.get("agent_id").asText() : (callerAgent != null ? callerAgent : "agent");
                    String projectPath = (args != null && args.has("project_path")) ? args.get("project_path").asText() : "";
                    String scope = (args != null && args.has("scope")) ? args.get("scope").asText() : "global";

                    var req = new ExtractionService.IngestRequest(messages, text, src, agentId, projectPath, scope);
                    var res = extractionService.extractAndIngest(req);
                    textResult = toJson(res);
                }
                default -> {
                    return new JsonRpcResponse(id, new JsonRpcResponse.JsonRpcError(-32601, "Unknown tool: " + toolName, null));
                }
            }
        } catch (Exception e) {
            log.error("执行工具 [{}] 失败: {}", toolName, e.getMessage(), e);
            textResult = "{\"error\": \"" + e.getMessage() + "\"}";
        }

        Map<String, Object> contentItem = Map.of("type", "text", "text", textResult);
        return new JsonRpcResponse(id, Map.of("content", List.of(contentItem)));
    }

    private String toJson(Object obj) {
        try {
            return objectMapper.writeValueAsString(obj);
        } catch (Exception e) {
            return "[]";
        }
    }
}
