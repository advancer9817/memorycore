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

    public boolean isRealModelOnline() {
        return realModelOnline;
    }

    public EmbeddingService(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(2))
                .build();
    }

    public float[] embedText(String text) {
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
            // 记录日志并静默降级为确定性哈希
            realModelOnline = false;
            return embedHashing(text, dim);
        }
    }

    private float[] embedOllama(String text) throws Exception {
        String endpoint = ollamaUrl.replaceAll("/+$", "") + "/api/embed";
        String payload = objectMapper.writeValueAsString(Map.of("model", modelName, "input", text));

        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(endpoint))
                .timeout(Duration.ofSeconds(3))
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

        float[] result = new float[dim];
        for (int i = 0; i < Math.min(dim, vecNode.size()); i++) {
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
