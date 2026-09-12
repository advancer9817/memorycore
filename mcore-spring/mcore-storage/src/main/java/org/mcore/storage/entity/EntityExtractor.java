package org.mcore.storage.entity;

import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 实体提取与别名归一（对标 Python `memorycore/storage/entities.py`）。
 *
 * Java 迁移后此能力整体缺失：`memory_entities` 表自 2026-09-10 起停止增长，
 * 而 `memories` 持续写入 —— 每新增一条记忆就多欠一截索引。
 */
@Component
public class EntityExtractor {

    /** 别名分组：同组内任意写法归一为同一 canonical 实体 */
    private static final String[][] ALIAS_GROUPS = {
            {"mcore", "mcore", "memorycore"},
            {"qdrant", "qdrant", "vector store", "vector_store"},
            {"sqlite", "sqlite", "sqlite3", "memory.sqlite3", "fts5"},
            {"ollama", "ollama", "nomic-embed-text", "nomic embed text"},
            {"mcp", "mcp", "model context protocol"},
            {"openmemory", "openmemory", "open memory", "mem0"},
    };

    /** 溯源标签不作为实体（它们是元数据，不是记忆内容主体） */
    private static final Pattern PROVENANCE_TAG = Pattern.compile(
            "^(extracted|rollup|atomic_fact|agent:.+|project:.+|windows|claude|hermes|codex|gemini|opencode)$",
            Pattern.CASE_INSENSITIVE);

    private static final Pattern TOKEN = Pattern.compile("[a-z0-9]+|[\\u4e00-\\u9fff]+");
    private static final Pattern PORT_NUM = Pattern.compile("^\\d{2,5}$");
    private static final Pattern FILE_EXT = Pattern.compile("\\.(sqlite3?|ya?ml|toml|json|db|py|md)$", Pattern.CASE_INSENSITIVE);

    private static final Pattern RE_URL = Pattern.compile("https?://[^\\s)'\"<>]+");
    private static final Pattern RE_PATH = Pattern.compile("(?<!\\w)/(?:[\\w.@+-]+/)*[\\w.@+-]+");
    private static final Pattern RE_FILE = Pattern.compile("\\b[\\w.-]+\\.(?:sqlite3?|ya?ml|toml|json|db|py|md)\\b", Pattern.CASE_INSENSITIVE);
    private static final Pattern RE_PORT = Pattern.compile("(?::|port\\s+|端口\\s*)(\\d{2,5})\\b", Pattern.CASE_INSENSITIVE);
    private static final Pattern RE_KNOWN = Pattern.compile(
            "\\b(?:mcore|memorycore|memory\\.sqlite3|qdrant|ollama|nomic-embed-text|openmemory|mem0|mcp|fts5)\\b",
            Pattern.CASE_INSENSITIVE);

    private static final Map<String, String> ALIAS_TO_CANONICAL = new LinkedHashMap<>();
    private static final Map<String, List<String>> CANONICAL_ALIASES = new LinkedHashMap<>();

    static {
        for (String[] group : ALIAS_GROUPS) {
            String canonical = normalizeEntity(group[0]);
            Set<String> normalized = new LinkedHashSet<>();
            for (int i = 1; i < group.length; i++) {
                String n = normalizeEntity(group[i]);
                if (!n.isBlank()) {
                    normalized.add(n);
                }
            }
            List<String> sorted = new ArrayList<>(normalized);
            sorted.sort(String::compareTo);
            CANONICAL_ALIASES.put(canonical, sorted);
            for (String alias : sorted) {
                ALIAS_TO_CANONICAL.put(alias, canonical);
            }
        }
    }

    /** 归一化：转小写、下划线/连字符转空格、仅保留字母数字与中文字符 */
    public static String normalizeEntity(String value) {
        String text = value == null ? "" : value.trim().toLowerCase(Locale.ROOT);
        text = text.replace("_", " ").replace("-", " ");
        Matcher m = TOKEN.matcher(text);
        List<String> parts = new ArrayList<>();
        while (m.find()) {
            parts.add(m.group());
        }
        return String.join(" ", parts);
    }

    /** 别名归一到 canonical 实体（如 `memorycore` → `mcore`） */
    public static String canonicalEntity(String value) {
        String normalized = normalizeEntity(value);
        return ALIAS_TO_CANONICAL.getOrDefault(normalized, normalized);
    }

    public static List<String> aliasesOf(String canonical) {
        return CANONICAL_ALIASES.getOrDefault(canonical, List.of(canonical));
    }

    private static String entityType(String value) {
        if (value.startsWith("http://") || value.startsWith("https://")) {
            return "url";
        }
        if (value.startsWith("/")) {
            return "path";
        }
        if (PORT_NUM.matcher(value).matches()) {
            return "port";
        }
        if (value.contains(".") && FILE_EXT.matcher(value).find()) {
            return "file";
        }
        return "concept";
    }

    private static double weight(String entityType) {
        switch (entityType) {
            case "path": return 1.0;
            case "url": return 0.95;
            case "port": return 0.9;
            case "file": return 0.9;
            case "concept": return 0.75;
            default: return 0.7;
        }
    }

    /** 从文本与标签中确定性抽取实体（不依赖 LLM） */
    public List<Map<String, Object>> extractEntities(String text, List<String> tags) {
        String source = text == null ? "" : text;
        List<String> candidates = new ArrayList<>();

        addAll(candidates, RE_URL, source, 0);
        addAll(candidates, RE_PATH, source, 0);
        addAll(candidates, RE_FILE, source, 0);
        addAll(candidates, RE_PORT, source, 1);
        addAll(candidates, RE_KNOWN, source, 0);

        if (tags != null) {
            for (String t : tags) {
                String s = t == null ? "" : t.trim();
                if (!s.isEmpty() && !PROVENANCE_TAG.matcher(s).matches()) {
                    candidates.add(s);
                }
            }
        }

        Map<String, Map<String, Object>> byNorm = new LinkedHashMap<>();
        for (String raw : candidates) {
            String cleaned = raw == null ? "" : raw.trim();
            cleaned = trimTrailing(cleaned);
            if (cleaned.isEmpty()) {
                continue;
            }
            String normalized = canonicalEntity(cleaned);
            if (normalized.isEmpty()) {
                continue;
            }
            String type = entityType(cleaned);
            double w = weight(type);
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("entity", cleaned);
            item.put("normalized_entity", normalized);
            item.put("aliases", aliasesOf(normalized));
            item.put("entity_type", type);
            item.put("weight", w);

            Map<String, Object> current = byNorm.get(normalized);
            if (current == null || w > ((Number) current.get("weight")).doubleValue()) {
                byNorm.put(normalized, item);
            }
        }

        List<Map<String, Object>> out = new ArrayList<>(byNorm.values());
        out.sort((a, b) -> Double.compare(
                ((Number) b.get("weight")).doubleValue(),
                ((Number) a.get("weight")).doubleValue()));
        return out;
    }

    private static void addAll(List<String> out, Pattern p, String source, int group) {
        Matcher m = p.matcher(source);
        while (m.find()) {
            out.add(m.group(group));
        }
    }

    /** 去除候选值尾部可能粘连的标点（对标 Python `.strip(".,;:)")` ） */
    private static String trimTrailing(String v) {
        int end = v.length();
        while (end > 0 && ".,;:)".indexOf(v.charAt(end - 1)) >= 0) {
            end--;
        }
        return v.substring(0, end);
    }
}
