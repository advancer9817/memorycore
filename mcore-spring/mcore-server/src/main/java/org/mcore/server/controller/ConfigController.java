package org.mcore.server.controller;

import org.mcore.server.service.ConfigService;
import org.springframework.web.bind.annotation.*;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 配置中心 REST 接口。
 *
 * 唯一事实源为磁盘 config.yaml，读写均落盘；不存在进程内内存副本。
 * 前端契约：{settings, llm:{llm,embedder}, strategy:{rule_curator,llm_curator,governance,extraction_strategy}}
 */
@RestController
@RequestMapping("/api/v1")
public class ConfigController {

    private final ConfigService configService;

    public ConfigController(ConfigService configService) {
        this.configService = configService;
    }

    @GetMapping("/config")
    public Map<String, Object> getConfig() {
        return configService.readUiConfig();
    }

    @PutMapping("/config")
    public Map<String, Object> updateConfig(@RequestBody(required = false) Map<String, Object> newConfig) {
        return configService.updateUiConfig(newConfig);
    }

    /** 恢复基线配置（前端 resetConfig 走 POST） */
    @RequestMapping(value = "/config/reset", method = {RequestMethod.POST, RequestMethod.GET, RequestMethod.PUT})
    public Map<String, Object> resetConfig() {
        return configService.reset();
    }

    /** 单独保存提取模型配置 */
    @PutMapping("/config/llm/extraction")
    public Map<String, Object> saveExtractionLlm(@RequestBody(required = false) Map<String, Object> body) {
        return configService.updateLlmSection("extraction", body);
    }

    /** 单独保存嵌入模型配置 */
    @PutMapping("/config/llm/embedding")
    public Map<String, Object> saveEmbeddingLlm(@RequestBody(required = false) Map<String, Object> body) {
        return configService.updateLlmSection("embedding", body);
    }

    /** 读取提取/嵌入段原始配置（便于设置页回显与排障） */
    @GetMapping("/config/llm/{section}")
    public Map<String, Object> getLlmSection(@PathVariable("section") String section) {
        String key = "embedding".equalsIgnoreCase(section) ? "embedding" : "extraction";
        Map<String, Object> raw = configService.raw();
        Map<String, Object> res = new LinkedHashMap<>();
        Object v = raw.get(key);
        res.put(key, v == null ? new LinkedHashMap<>() : v);
        return res;
    }

    /** 原始配置全文（排障用） */
    @GetMapping("/config/raw")
    public Map<String, Object> getRawConfig() {
        return configService.raw();
    }
}
