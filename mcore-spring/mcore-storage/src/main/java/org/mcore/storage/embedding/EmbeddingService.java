package org.mcore.storage.embedding;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.Map;

/**
 * 工业级双模 Embedding 向量生成服务
 * 1. 优先调用 OpenAI 兼容 API / 本地 Ollama 端口 (:11434)
 * 2. 遇网络不可达、模型未就绪或未启动时，平滑降级至 SHA-256 伪哈希确定性特征向量 (零外部依赖，算法与 Python 版 100% 字节对齐)
 */
@Service
public class EmbeddingService {
    private static final Logger log = LoggerFactory.getLogger(EmbeddingService.class);

    private final HttpClient httpClient;
    private final ObjectMapper objectMapper;
    private final org.mcore.storage.config.ConfigFileStore configStore;

    @Value("${mcore.embedding.ollama-url:http://127.0.0.1:11434}")
    private String ollamaUrl;

    @Value("${mcore.embedding.model:nomic-embed-text}")
    private String modelName;

    @Value("${mcore.embedding.api-url:}")
    private String apiUrl;

    @Value("${mcore.embedding.api-key:}")
    private String apiKey;

    @Value("${mcore.embedding.dim:768}")
    private int dim;

    private volatile boolean realModelOnline = false;

    /**
     * 单条嵌入的超时秒数。
     *
     * 修复：原先硬编码 3 秒，而 config.yaml 中 `embedding.timeout: 30` 从未被消费。
     * bge-m3 在受限 CPU 上单条嵌入需 1–2 秒，回填或并发时更容易超过 3 秒 ——
     * 超时即静默降级为哈希向量，使新写入的记忆悄悄失去语义检索能力。
     */
    @Value("${mcore.embedding.timeout:30}")
    private int timeoutSeconds = 30;

    /** 降级计数器与最近一次失败原因（可观测性：此前降级完全无迹可循） */
    private final java.util.concurrent.atomic.AtomicLong degradationCount =
            new java.util.concurrent.atomic.AtomicLong(0);
    private volatile String lastFallbackReason = null;

    public boolean isRealModelOnline() {
        return realModelOnline;
    }

    public long getDegradationCount() {
        return degradationCount.get();
    }

    public String getLastFallbackReason() {
        return lastFallbackReason;
    }

    public EmbeddingService(ObjectMapper objectMapper,
                            org.mcore.storage.config.ConfigFileStore configStore) {
        this.configStore = configStore;
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(2))
                .build();
    }

    /**
     * 从磁盘配置热刷新嵌入参数（设置页改动即时生效）。
     * 注意：不热更新 dim —— 向量列维度固定为 768，运行期变更会导致写入失败，
     * 维度调整必须伴随数据重建，属运维操作而非在线配置。
     */
    private void refreshRuntimeConfig() {
        try {
            Map<String, Object> s = configStore.embeddingSettings();
            if (s.isEmpty()) {
                return;
            }
            this.ollamaUrl = configStore.str(s, "ollama_url", this.ollamaUrl);
            this.modelName = configStore.str(s, "model", this.modelName);
            this.apiUrl = configStore.str(s, "api_url", this.apiUrl);
            this.apiKey = configStore.str(s, "api_key", this.apiKey);
            // 消费 config.yaml 的 embedding.timeout（原先该配置项被硬编码 3 秒完全覆盖）
            Object t = s.get("timeout");
            if (t instanceof Number n && n.intValue() > 0) {
                this.timeoutSeconds = n.intValue();
            }
        } catch (Exception e) {
            log.warn("读取运行期嵌入配置失败，沿用启动配置: {}", e.getMessage());
        }
    }

    public float[] embedText(String text) {
        refreshRuntimeConfig();
        if (text == null || text.isBlank()) {
            return new float[dim];
        }

        // 1. 若配置了 OpenAI API 端点
        if (apiUrl != null && !apiUrl.isBlank()) {
            try {
                float[] vec = embedOpenAi(text);
                realModelOnline = true;
                return vec;
            } catch (Exception e) {
                log.warn("OpenAI-compatible embedding 失败 ({}), 尝试 Ollama", e.getMessage());
            }
        }

        // 2. 尝试本地 Ollama 端点
        try {
            float[] vec = embedOllama(text);
            realModelOnline = true;
            return vec;
        } catch (Exception e) {
            // 降级为确定性哈希 —— 但必须留痕：此前既无日志也无审计，
            // 导致"新写入记忆被静默降级"这一事实长期不可观测。
            realModelOnline = false;
            degradationCount.incrementAndGet();
            lastFallbackReason = e.getMessage();
            log.warn("Ollama embedding 失败，降级为哈希向量（第 {} 次）: endpoint={} model={} err={}",
                    degradationCount.get(), ollamaUrl, modelName, e.getMessage());
            return embedHashing(text, dim);
        }
    }

    private float[] embedOllama(String text) throws Exception {
        String endpoint = ollamaUrl.replaceAll("/+$", "") + "/api/embed";
        String payload = objectMapper.writeValueAsString(Map.of("model", modelName, "input", text));

        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(endpoint))
                .timeout(Duration.ofSeconds(Math.max(5, timeoutSeconds)))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(payload))
                .build();

        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() != 200) {
            throw new RuntimeException("Ollama HTTP " + response.statusCode());
        }

        JsonNode root = objectMapper.readTree(response.body());
        JsonNode vecNode = root.has("embeddings") ? root.get("embeddings").get(0) : root.get("embedding");
        if (vecNode == null || !vecNode.isArray()) {
            throw new RuntimeException("Ollama 响应缺失 embedding 数组");
        }
        // 维度不符时明确报错，不再静默补零（补零会产出语义错误的向量且无从察觉）
        if (vecNode.size() != dim) {
            throw new RuntimeException("嵌入维度不符: 模型返回 " + vecNode.size() + "，期望 " + dim);
        }

        float[] result = new float[dim];
        for (int i = 0; i < dim; i++) {
            result[i] = (float) vecNode.get(i).asDouble();
        }
        return normalize(result);
    }

    private float[] embedOpenAi(String text) throws Exception {
        String endpoint = apiUrl.replaceAll("/+$", "");
        if (!endpoint.endsWith("/embeddings")) {
            endpoint += "/embeddings";
        }
        String payload = objectMapper.writeValueAsString(Map.of("model", modelName, "input", text));

        var reqBuilder = HttpRequest.newBuilder()
                .uri(URI.create(endpoint))
                .timeout(Duration.ofSeconds(5))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(payload));

        if (apiKey != null && !apiKey.isBlank()) {
            reqBuilder.header("Authorization", "Bearer " + apiKey);
        }

        HttpResponse<String> response = httpClient.send(reqBuilder.build(), HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() != 200) {
            throw new RuntimeException("OpenAI HTTP " + response.statusCode());
        }

        JsonNode root = objectMapper.readTree(response.body());
        JsonNode vecNode = root.get("data").get(0).get("embedding");
        float[] result = new float[dim];
        for (int i = 0; i < Math.min(dim, vecNode.size()); i++) {
            result[i] = (float) vecNode.get(i).asDouble();
        }
        return normalize(result);
    }

    /**
     * 确定性伪哈希向量生成 (算法与 Python _embed_hashing 100% 字节对齐)
     */
    /**
     * 批量嵌入：单次 HTTP 请求提交多个文本，由 ollama 在一次前向传播中处理。
     *
     * 为什么需要：逐条调用在 2 核环境下约 1.9s/条（4836 条约需 2.5 小时）；
     * 批量提交可让模型在一次推理中处理整批，吞吐显著提升。
     *
     * @return 与入参顺序一致的向量列表；单条失败时对应位置为 null
     */
    public java.util.List<float[]> embedBatch(java.util.List<String> texts) throws Exception {
        refreshRuntimeConfig();
        java.util.List<float[]> out = new java.util.ArrayList<>();
        if (texts == null || texts.isEmpty()) {
            return out;
        }

        // 仅在 ollama 通道可用且未配置 OpenAI 端点时走批量路径
        boolean useOllama = (apiUrl == null || apiUrl.isBlank());
        if (!useOllama) {
            for (String t : texts) {
                out.add(embedText(t));
            }
            return out;
        }

        try {
            String endpoint = ollamaUrl.replaceAll("/+$", "") + "/api/embed";
            String payload = objectMapper.writeValueAsString(Map.of("model", modelName, "input", texts));
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(endpoint))
                    .timeout(Duration.ofSeconds(Math.max(60, 30 * texts.size())))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(payload, StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() != 200) {
                throw new RuntimeException("Ollama batch HTTP " + response.statusCode());
            }
            JsonNode root = objectMapper.readTree(response.body());
            JsonNode arr = root.get("embeddings");
            if (arr == null || !arr.isArray()) {
                throw new RuntimeException("Ollama 批量响应缺失 embeddings");
            }
            for (JsonNode vecNode : arr) {
                if (vecNode == null || !vecNode.isArray()) {
                    out.add(null);
                    continue;
                }
                float[] v = new float[dim];
                int n = Math.min(vecNode.size(), dim);
                for (int i = 0; i < n; i++) {
                    v[i] = (float) vecNode.get(i).asDouble();
                }
                out.add(v);
            }
            realModelOnline = true;
            // 数量不足时补齐占位，保证与入参对齐
            while (out.size() < texts.size()) {
                out.add(null);
            }
            return out;
        } catch (Exception e) {
            log.warn("批量嵌入失败，回退逐条: {}", e.getMessage());
            out.clear();
            for (String t : texts) {
                try {
                    out.add(embedText(t));
                } catch (Exception ex) {
                    out.add(null);
                }
            }
            return out;
        }
    }

    public float[] embedHashing(String text, int targetDim) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] h = md.digest(text.getBytes(StandardCharsets.UTF_8));
            float[] vals = new float[targetDim];
            double sumSq = 0;
            for (int i = 0; i < targetDim; i++) {
                int b = h[i % 32] & 0xFF;
                double angle = (b / 255.0) * 2 * Math.PI + i;
                vals[i] = (float) Math.sin(angle);
                sumSq += vals[i] * vals[i];
            }
            float norm = (float) Math.sqrt(sumSq);
            if (norm == 0) norm = 1.0f;
            for (int i = 0; i < targetDim; i++) {
                vals[i] /= norm;
            }
            return vals;
        } catch (Exception e) {
            throw new RuntimeException("SHA-256 Hashing 向量计算失败", e);
        }
    }

    private float[] normalize(float[] v) {
        double sumSq = 0;
        for (float val : v) {
            sumSq += val * val;
        }
        float norm = (float) Math.sqrt(sumSq);
        if (norm == 0) norm = 1.0f;
        float[] res = new float[v.length];
        for (int i = 0; i < v.length; i++) {
            res[i] = v[i] / norm;
        }
        return res;
    }
}
