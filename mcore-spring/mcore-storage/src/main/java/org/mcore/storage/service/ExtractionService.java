package org.mcore.storage.service;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.mcore.common.model.MemoryDO;
import org.mcore.storage.embedding.EmbeddingService;
import org.mcore.storage.repository.MemoryRepository;
import org.mcore.storage.search.HybridSearchService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.LocalDate;
import java.util.*;

/**
 * 工业级大模型对话上下文提炼与记忆回写服务
 * 1. 接收多轮会话消息 messages 或文本 text
 * 2. 调用 CPA (OpenAI 兼容接口) 进行事实抽取与分类打标
 * 3. 对提炼事实生成 768 维特征向量，执行 pgvector 语义去重与演进替换
 * 4. 幂等回写至 PostgreSQL memories 表并返回结构化审计报告
 */
@Service
public class ExtractionService {

    private static final Logger log = LoggerFactory.getLogger(ExtractionService.class);

    private final EmbeddingService embeddingService;
    private final HybridSearchService hybridSearchService;
    private final MemoryRepository memoryRepository;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;
    private final org.mcore.storage.config.ConfigFileStore configStore;

    @Value("${mcore.extraction.base-url:http://127.0.0.1:8317/v1}")
    private String baseUrl;

    @Value("${mcore.extraction.api-key:sk}")
    private String apiKey;

    @Value("${mcore.extraction.model:gemini-3.8-flash}")
    private String model;

    @Value("${mcore.extraction.timeout:90}")
    private int timeoutSeconds;

    public record IngestRequest(
            List<Map<String, String>> messages,
            String text,
            String source,
            String agentId,
            String projectPath,
            String scope
    ) {}

    public record IngestResult(
            int added,
            int updated,
            int skipped,
            int errors,
            @JsonProperty("added_titles") List<String> addedTitles,
            @JsonProperty("updated_titles") List<String> updatedTitles,
            @JsonProperty("skipped_details") List<Map<String, Object>> skippedDetails,
            @JsonProperty("elapsed_s") double elapsedS,
            @JsonProperty("extraction_elapsed_s") double extractionElapsedS,
            boolean degraded,
            String error
    ) {}

    public ExtractionService(EmbeddingService embeddingService,
                             HybridSearchService hybridSearchService,
                             MemoryRepository memoryRepository,
                             ObjectMapper objectMapper,
                             org.mcore.storage.config.ConfigFileStore configStore) {
        this.configStore = configStore;
        this.embeddingService = embeddingService;
        this.hybridSearchService = hybridSearchService;
        this.memoryRepository = memoryRepository;
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(5))
                .build();
    }

    /**
     * 从磁盘配置热刷新提取参数。设置页改动即时生效，无需重启。
     * config.yaml 中存在非空值则覆盖启动配置，否则沿用 @Value 兜底。
     */
    private void refreshRuntimeConfig() {
        try {
            Map<String, Object> s = configStore.extractionSettings();
            if (s.isEmpty()) {
                return;
            }
            this.baseUrl = configStore.str(s, "base_url", this.baseUrl);
            this.apiKey = configStore.str(s, "api_key", this.apiKey);
            this.model = configStore.str(s, "model", this.model);
            this.timeoutSeconds = configStore.intVal(s, "timeout", this.timeoutSeconds);
        } catch (Exception e) {
            log.warn("读取运行期提取配置失败，沿用启动配置: {}", e.getMessage());
        }
    }

    public IngestResult extractAndIngest(IngestRequest req) {
        long tStart = System.currentTimeMillis();
        refreshRuntimeConfig();
        List<Map<String, String>> msgs = req.messages();
        String text = req.text();
        String agentId = (req.agentId() != null && !req.agentId().isBlank()) ? req.agentId() : "agent";
        String src = (req.source() != null && !req.source().isBlank()) ? req.source() : "ingest";
        String projectPath = req.projectPath() != null ? req.projectPath() : "";
        String scope = (req.scope() != null && !req.scope().isBlank()) ? req.scope() : "global";

        StringBuilder transcript = new StringBuilder();
        if (msgs != null && !msgs.isEmpty()) {
            for (Map<String, String> m : msgs) {
                if (m == null) continue;
                String role = m.getOrDefault("role", "user");
                String content = m.getOrDefault("content", "");
                if (content != null && !content.isBlank()) {
                    transcript.append(role).append(": ").append(content.strip()).append("\n\n");
                }
            }
        } else if (text != null && !text.isBlank()) {
            transcript.append("user: ").append(text.strip()).append("\n\n");
        }

        String transcriptStr = transcript.toString().strip();
        if (transcriptStr.isBlank()) {
            return new IngestResult(0, 0, 0, 0, List.of(), List.of(), List.of(), 0.0, 0.0, false, null);
        }

        // 超过 16000 字符保留首尾关键对话
        if (transcriptStr.length() > 16000) {
            transcriptStr = transcriptStr.substring(0, 4000) + "\n\n... [中间调试与输出省略] ...\n\n" + transcriptStr.substring(transcriptStr.length() - 8000);
        }

        double extractionElapsedS = 0.0;
        List<String> addedTitles = new ArrayList<>();
        List<String> updatedTitles = new ArrayList<>();
        List<Map<String, Object>> skippedDetails = new ArrayList<>();
        int added = 0;
        int updated = 0;
        int skipped = 0;
        int errors = 0;

        try {
            String systemPrompt = buildSystemPrompt();
            String endpoint = resolveCompletionsUrl(baseUrl);

            Map<String, Object> payload = Map.of(
                    "model", model,
                    "messages", List.of(
                            Map.of("role", "system", "content", systemPrompt),
                            Map.of("role", "user", "content", transcriptStr)
                    ),
                    "temperature", 0.1,
                    "max_tokens", 4096,
                    "response_format", Map.of("type", "json_object")
            );

            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(endpoint))
                    .timeout(Duration.ofSeconds(timeoutSeconds))
                    .header("Content-Type", "application/json")
                    .header("Authorization", "Bearer " + apiKey)
                    .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(payload), StandardCharsets.UTF_8))
                    .build();

            long tLlmStart = System.currentTimeMillis();
            HttpResponse<String> response = null;
            Exception lastLlmEx = null;
            for (int attempt = 0; attempt < 2; attempt++) {
                try {
                    response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
                    if (response.statusCode() == 200) {
                        lastLlmEx = null;
                        break;
                    }
                    log.warn("CPA chat/completions 第 {} 次调用返回非200: HTTP {}", attempt + 1, response.statusCode());
                } catch (Exception ex) {
                    lastLlmEx = ex;
                    log.warn("CPA chat/completions 第 {} 次调用异常: {}", attempt + 1, ex.getMessage());
                }
            }
            long tLlmEnd = System.currentTimeMillis();
            extractionElapsedS = (tLlmEnd - tLlmStart) / 1000.0;

            if (response == null || response.statusCode() != 200) {
                String errMsg = lastLlmEx != null ? lastLlmEx.getMessage() : (response != null ? "CPA HTTP " + response.statusCode() : "LLM call failed");
                log.error("CPA chat/completions 提取失败: {}", errMsg);
                double totalS = (System.currentTimeMillis() - tStart) / 1000.0;
                return new IngestResult(0, 0, 0, 1, List.of(), List.of(), List.of(), totalS, extractionElapsedS, true, errMsg);
            }

            JsonNode root = objectMapper.readTree(response.body());
            JsonNode choices = root.get("choices");
            if (choices == null || !choices.isArray() || choices.isEmpty()) {
                double totalS = (System.currentTimeMillis() - tStart) / 1000.0;
                return new IngestResult(0, 0, 0, 1, List.of(), List.of(), List.of(), totalS, extractionElapsedS, true, "Empty choices from LLM");
            }

            String rawContent = choices.get(0).path("message").path("content").asText("");
            String cleanJson = cleanJsonResponse(rawContent);
            JsonNode memoryRoot = objectMapper.readTree(cleanJson);
            JsonNode memoryList = memoryRoot.path("memory");

            if (memoryList != null && memoryList.isArray()) {
                for (JsonNode factNode : memoryList) {
                    try {
                        String title = factNode.path("title").asText("").trim();
                        String content = factNode.path("content").asText("").trim();
                        String type = factNode.path("type").asText("decision").trim();
                        double importance = factNode.has("importance") ? factNode.get("importance").asDouble(0.7) : 0.7;
                        double confidence = factNode.has("confidence") ? factNode.get("confidence").asDouble(0.8) : 0.8;

                        if (title.isBlank() || content.isBlank() || importance < 0.3) {
                            continue;
                        }

                        List<String> tags = new ArrayList<>();
                        if (factNode.has("tags") && factNode.get("tags").isArray()) {
                            for (JsonNode tagNode : factNode.get("tags")) {
                                String t = tagNode.asText("").trim();
                                if (!t.isBlank() && !tags.contains(t)) tags.add(t);
                            }
                        }
                        if (!tags.contains(type)) tags.add(type);
                        if (!agentId.isBlank() && !tags.contains("agent:" + agentId)) tags.add("agent:" + agentId);

                        float[] vec = embeddingService.embedText(title + " " + content);

                        // 向量双阈值去重：检索最相似的 3 条已知活跃事实
                        List<HybridSearchService.SearchHit> hits = hybridSearchService.pureVectorSearch(vec, 3);
                        HybridSearchService.SearchHit topHit = hits.isEmpty() ? null : hits.get(0);

                        if (topHit != null && topHit.vectorScore() >= 0.92) {
                            // 语义高度重合，执行跳过 (skip)
                            skipped++;
                            skippedDetails.add(Map.of(
                                    "title", title,
                                    "reason", "vector_duplicate",
                                    "similarity", topHit.vectorScore(),
                                    "existing_id", topHit.record().getId()
                            ));
                        } else if (topHit != null && topHit.vectorScore() >= 0.85) {
                            // 语义局部演进，执行更新覆盖 (update)
                            MemoryDO existing = topHit.record();
                            double newImp = Math.max(importance, existing.getImportance() != null ? existing.getImportance() : 0.5);
                            memoryRepository.update(existing.getId(), content, title, newImp, "active");
                            updated++;
                            updatedTitles.add(title);
                        } else {
                            // 独立增量事实，执行新增落库 (insert)
                            MemoryDO record = new MemoryDO();
                            record.setId("mem_" + UUID.randomUUID().toString().replace("-", "").substring(0, 16));
                            record.setTitle(title.length() > 100 ? title.substring(0, 97) + "..." : title);
                            record.setContent(content);
                            record.setType(type);
                            record.setScope(scope);
                            record.setSource(src);
                            record.setSourceAgent(agentId);
                            record.setProjectPath(projectPath);
                            record.setConfidence(confidence);
                            record.setImportance(importance);
                            record.setStatus("active");
                            record.setTags(tags);
                            record.setEmbedding(vec);

                            memoryRepository.insert(record);
                            added++;
                            addedTitles.add(title);
                        }
                    } catch (Exception itemEx) {
                        log.warn("处理单条提取事实异常: {}", itemEx.getMessage(), itemEx);
                        errors++;
                    }
                }
            }
        } catch (Exception e) {
            log.error("提取与回写执行异常: {}", e.getMessage(), e);
            errors++;
            double totalS = (System.currentTimeMillis() - tStart) / 1000.0;
            return new IngestResult(added, updated, skipped, errors, addedTitles, updatedTitles, skippedDetails, totalS, extractionElapsedS, true, e.getMessage());
        }

        double totalS = (System.currentTimeMillis() - tStart) / 1000.0;
        return new IngestResult(added, updated, skipped, errors, addedTitles, updatedTitles, skippedDetails, totalS, extractionElapsedS, false, null);
    }

    private String buildSystemPrompt() {
        String today = LocalDate.now().toString();
        return """
你是一个精准的工程对话事实提取器。
你的任务是从开发者与 AI 助手的对话中提取所有值得长期记住的事实。
提取的事实将在未来对话中作为上下文注入，帮助助手快速理解项目状态和用户偏好。

# 分析范围
分析完整对话（用户和助手的消息）。提取：
- 用户的意图、决策、请求中揭示的事实
- 助手回复中确认的技术事实：Bug 根因、代码变更、修复方案、架构决策
不提取：寒暄、感谢、进度更新、助手的通用解释

# 提取原则与边界（三必存、四不存）
## 三必存（重点捕获）：
1. 用户明确纠偏与规范：用户纠正 AI 行为、表达明确习惯偏好（\"以后改用 X\"、\"严禁 Y\"）必须提取为 decision/feedback/user_profile。
2. 实测验证的环境事实：经过排查确认生效的配置、路径、端口、环境变量、命令行参数。
3. 架构与业务定论：经过讨论最终确立的技术方案、重构结论、设计取舍。

## 四不存（严禁产生噪音）：
1. 过程报错与试错排查日志（中间堆栈、临时报错信息严禁作为长期记忆入库）。
2. 通用百科常识与基础语法解释（如“Python如何遍历字典”等通用知识不存）。
3. 未决推测与临时想法（仅存最终确认的结论）。
4. 与现有已知事实完全重复、无增量信息的琐碎记录。

# 输出格式
{
  "memory": [
    {
      "title": "不超过80字符的语义摘要",
      "content": "自包含的完整描述事实内容，50-300字符",
      "type": "decision",
      "importance": 0.8,
      "confidence": 0.85,
      "tags": ["tag1", "tag2"]
    }
  ]
}

## type 必须是以下之一：
- decision: 技术决策、选择的方案、放弃的方案及原因
- environment_fact: 环境配置、路径、端口、版本、依赖关系
- bug_fix: Bug 根因分析、修复方案、涉及的文件
- user_profile: 用户偏好、工作习惯、技术栈、角色
- project_memory: 项目状态、架构变更、里程碑、进度
- feedback: 用户对 AI 行为的纠正或确认（\"不要这样做\"、\"就这样\"）
- skill_learned: 可复用的工作流程、模式、技巧

# 规则
- 今天日期是 %s。
- 用中文记录事实。技术术语、专有名词、版本号保持原文不翻译。
- 无值得提取的内容时返回：{"memory": []}
- 仅返回合法 JSON，严禁 Markdown 代码块包裹，严禁任何额外解释文字。
- importance < 0.3 的事实不要输出。
""".formatted(today);
    }

    private String cleanJsonResponse(String raw) {
        if (raw == null) return "{\"memory\":[]}";
        String s = raw.strip();
        if (s.startsWith("```")) {
            int firstNewline = s.indexOf('\n');
            if (firstNewline != -1) {
                s = s.substring(firstNewline + 1);
            }
            if (s.endsWith("```")) {
                s = s.substring(0, s.length() - 3).strip();
            }
        }
        int firstBrace = s.indexOf('{');
        int lastBrace = s.lastIndexOf('}');
        if (firstBrace != -1 && lastBrace != -1 && lastBrace > firstBrace) {
            return s.substring(firstBrace, lastBrace + 1);
        }
        return s;
    }

    private String resolveCompletionsUrl(String base) {
        if (base == null || base.isBlank()) {
            return "http://127.0.0.1:8317/v1/chat/completions";
        }
        String clean = base.replaceAll("/+$", "");
        String path = clean.contains("://") ? clean.substring(clean.indexOf("://") + 3) : clean;
        if (!path.matches(".*/v\\d+.*")) {
            return clean + "/v1/chat/completions";
        }
        return clean + "/chat/completions";
    }
}
