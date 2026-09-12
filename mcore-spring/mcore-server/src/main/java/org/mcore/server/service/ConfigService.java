package org.mcore.server.service;

import org.mcore.storage.config.ConfigFileStore;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.*;

/**
 * 配置中心门面：负责「磁盘 YAML <-> 前端三层契约」的映射，文件读写委托给 ConfigFileStore。
 *
 * 前端契约：{settings, llm:{llm,embedder}, strategy:{rule_curator,llm_curator,governance,extraction_strategy}}
 */
@Service
public class ConfigService {

    private final ConfigFileStore store;
    private final Path configPath;
    private final Path defaultPath;

    public ConfigService(ConfigFileStore store) {
        this.store = store;
        this.configPath = store.getConfigPath();
        this.defaultPath = configPath.resolveSibling("config.default.yaml");
    }

    public Path getConfigPath() {
        return configPath;
    }

    /** 脱敏哨兵：前端回显时用它替代真实密钥；写回时该值被忽略，不会覆盖真实密钥 */
    public static final String REDACTED = "[REDACTED]";

    public Map<String, Object> raw() {
        return store.raw();
    }

    /**
     * 脱敏后的原始配置，供 `/api/v1/config/raw` 与设置页回显。
     *
     * 修复：此前该接口原样返回 config.yaml 全文，包含 extraction.api_key 与
     * database.password（明文口令），且属数据面路径 → 默认租户免鉴权即可读取。
     */
    public Map<String, Object> maskedRaw() {
        Map<String, Object> cfg = store.raw();
        maskSection(cfg, "extraction", "api_key");
        maskSection(cfg, "embedding", "api_key");
        maskSection(cfg, "database", "password");
        return cfg;
    }

    @SuppressWarnings("unchecked")
    private void maskSection(Map<String, Object> cfg, String section, String field) {
        Object sec = cfg.get(section);
        if (sec instanceof Map) {
            Map<String, Object> m = (Map<String, Object>) sec;
            Object v = m.get(field);
            if (v != null && !String.valueOf(v).isBlank()) {
                m.put(field, REDACTED);
            }
        }
    }

    /** 判断是否为需要跳过的脱敏哨兵值 */
    private boolean isRedacted(Object v) {
        return v != null && REDACTED.equals(String.valueOf(v).trim());
    }

    /** 回显时用哨兵替换非空密钥，空值保持为空以便前端区分"未设置" */
    private Object maskValue(Object v) {
        if (v == null || String.valueOf(v).isBlank()) {
            return v;
        }
        return REDACTED;
    }

    // ==================== 读 ====================

    /** 映射为前端契约 */
    public Map<String, Object> readUiConfig() {
        Map<String, Object> cfg = store.raw();

        // ---- settings ----
        Map<String, Object> settings = new LinkedHashMap<>();
        settings.put("custom_instructions", cfg.get("custom_instructions"));
        settings.put("output_language", cfg.getOrDefault("output_language", "zh"));

        // ---- llm.llm ← extraction ----
        Map<String, Object> extraction = store.section("extraction");
        Map<String, Object> llmConfig = new LinkedHashMap<>();
        llmConfig.put("model", extraction.get("model"));
        llmConfig.put("temperature", extraction.get("temperature"));
        llmConfig.put("max_tokens", extraction.get("max_tokens"));
        llmConfig.put("api_key", maskValue(extraction.get("api_key")));
        String llmProvider = inferProvider(extraction);
        if ("ollama".equals(llmProvider)) {
            llmConfig.put("ollama_base_url", extraction.get("base_url"));
        }
        Map<String, Object> llmBlock = new LinkedHashMap<>();
        llmBlock.put("provider", llmProvider);
        llmBlock.put("config", llmConfig);

        // ---- llm.embedder ← embedding ----
        Map<String, Object> embedding = store.section("embedding");
        Map<String, Object> embedderConfig = new LinkedHashMap<>();
        embedderConfig.put("model", embedding.get("model"));
        embedderConfig.put("api_key", maskValue(embedding.get("api_key")));
        embedderConfig.put("ollama_base_url", embedding.get("ollama_url"));
        embedderConfig.put("dim", embedding.get("dim"));
        Map<String, Object> embedderBlock = new LinkedHashMap<>();
        embedderBlock.put("provider", embedding.getOrDefault("provider", "auto"));
        embedderBlock.put("config", embedderConfig);

        Map<String, Object> llm = new LinkedHashMap<>();
        llm.put("llm", llmBlock);
        llm.put("embedder", embedderBlock);

        // ---- strategy：段名 1:1 透传 ----
        Map<String, Object> strategy = new LinkedHashMap<>();
        strategy.put("rule_curator", cfg.getOrDefault("rule_curator", new LinkedHashMap<>()));
        strategy.put("llm_curator", cfg.getOrDefault("llm_curator", new LinkedHashMap<>()));
        strategy.put("governance", cfg.getOrDefault("governance", new LinkedHashMap<>()));
        strategy.put("extraction_strategy", cfg.getOrDefault("extraction_strategy", new LinkedHashMap<>()));
        // 主体上下文：此前既不在读取面也不在写入白名单，配置存在却无任何消费者
        strategy.put("subject_context", cfg.getOrDefault("subject_context", new LinkedHashMap<>()));

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("settings", settings);
        out.put("llm", llm);
        out.put("strategy", strategy);
        return out;
    }

    // ==================== 写 ====================

    @SuppressWarnings("unchecked")
    public Map<String, Object> updateUiConfig(Map<String, Object> patch) {
        if (patch == null || patch.isEmpty()) {
            return readUiConfig();
        }
        Map<String, Object> cfg = store.raw();

        Object settingsObj = patch.get("settings");
        if (settingsObj instanceof Map) {
            Map<String, Object> s = (Map<String, Object>) settingsObj;
            if (s.containsKey("output_language")) {
                cfg.put("output_language", s.get("output_language"));
            }
            if (s.containsKey("custom_instructions")) {
                cfg.put("custom_instructions", s.get("custom_instructions"));
            }
        }

        Object llmObj = patch.get("llm");
        if (llmObj instanceof Map) {
            Map<String, Object> llmMap = (Map<String, Object>) llmObj;
            if (llmMap.get("llm") instanceof Map) {
                applyLlmProvider(cfg, "extraction", (Map<String, Object>) llmMap.get("llm"));
            }
            if (llmMap.get("embedder") instanceof Map) {
                applyLlmProvider(cfg, "embedding", (Map<String, Object>) llmMap.get("embedder"));
            }
        }

        Object strategyObj = patch.get("strategy");
        if (strategyObj instanceof Map) {
            Map<String, Object> st = (Map<String, Object>) strategyObj;
            for (String section : new String[]{"rule_curator", "llm_curator", "governance", "extraction_strategy", "subject_context"}) {
                Object v = st.get(section);
                if (v instanceof Map) {
                    cfg.put(section, v);
                }
            }
        }

        store.write(cfg);
        return readUiConfig();
    }

    /** 单独更新 extraction / embedding 段 */
    @SuppressWarnings("unchecked")
    public Map<String, Object> updateLlmSection(String which, Map<String, Object> body) {
        String section = "embedding".equalsIgnoreCase(which) ? "embedding" : "extraction";
        Map<String, Object> cfg = store.raw();
        Map<String, Object> payload = body == null ? new LinkedHashMap<>() : new LinkedHashMap<>(body);
        // 兼容 {provider, config:{...}} 包装形式
        if (payload.get("config") instanceof Map) {
            Map<String, Object> inner = (Map<String, Object>) payload.get("config");
            Object provider = payload.get("provider");
            payload = new LinkedHashMap<>(inner);
            if (provider != null) {
                payload.put("provider", provider);
            }
        }
        applyLlmProvider(cfg, section, payload);
        store.write(cfg);
        return readUiConfig();
    }

    /** 恢复基线配置：首次调用将当前配置固化为 config.default.yaml */
    public Map<String, Object> reset() {
        try {
            if (!Files.exists(defaultPath)) {
                if (Files.exists(configPath)) {
                    Files.copy(configPath, defaultPath, StandardCopyOption.REPLACE_EXISTING);
                } else {
                    throw new IllegalStateException("配置文件与基线均不存在: " + configPath);
                }
            }
            Files.copy(defaultPath, configPath, StandardCopyOption.REPLACE_EXISTING);
            store.write(store.raw()); // 触发缓存失效并规范写入
        } catch (IOException e) {
            throw new IllegalStateException("恢复默认配置失败: " + e.getMessage(), e);
        }
        return readUiConfig();
    }

    // ==================== 内部 ====================

    @SuppressWarnings("unchecked")
    private void applyLlmProvider(Map<String, Object> cfg, String section, Map<String, Object> payload) {
        Map<String, Object> target = new LinkedHashMap<>();
        Object existing = cfg.get(section);
        if (existing instanceof Map) {
            target.putAll((Map<String, Object>) existing);
        }

        Object provider = payload.get("provider");
        if (provider != null) {
            target.put("provider", provider);
        }

        if ("embedding".equals(section)) {
            putIfPresent(target, "model", payload.get("model"));
            putIfPresent(target, "api_key", payload.get("api_key"));
            if (payload.containsKey("ollama_base_url")) {
                target.put("ollama_url", payload.get("ollama_base_url"));
            }
            putIfPresent(target, "dim", payload.get("dim"));
            for (String k : new String[]{"api_url", "fallback_provider", "timeout", "sentence_transformers_model"}) {
                if (payload.containsKey(k)) {
                    target.put(k, payload.get(k));
                }
            }
        } else {
            putIfPresent(target, "model", payload.get("model"));
            putIfPresent(target, "temperature", payload.get("temperature"));
            putIfPresent(target, "max_tokens", payload.get("max_tokens"));
            putIfPresent(target, "api_key", payload.get("api_key"));
            if (payload.containsKey("ollama_base_url")) {
                target.put("base_url", payload.get("ollama_base_url"));
            }
            if (payload.containsKey("base_url")) {
                target.put("base_url", payload.get("base_url"));
            }
            for (String k : new String[]{"timeout"}) {
                if (payload.containsKey(k)) {
                    target.put(k, payload.get(k));
                }
            }
        }
        cfg.put(section, target);
    }

    private void putIfPresent(Map<String, Object> target, String key, Object value) {
        if (value == null) {
            return;
        }
        // 脱敏哨兵不得写回：前端回显的是 [REDACTED]，若按原值落盘会把真实密钥覆盖掉
        if ("api_key".equals(key) && isRedacted(value)) {
            return;
        }
        target.put(key, value);
    }

    private String inferProvider(Map<String, Object> section) {
        Object explicit = section.get("provider");
        if (explicit != null && !String.valueOf(explicit).isBlank()) {
            return String.valueOf(explicit);
        }
        String baseUrl = String.valueOf(section.getOrDefault("base_url", ""));
        if (baseUrl.contains("11434") || baseUrl.toLowerCase().contains("ollama")) {
            return "ollama";
        }
        return "openai";
    }
}
