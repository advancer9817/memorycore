package org.mcore.storage.subject;

import org.mcore.storage.config.ConfigFileStore;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.stereotype.Service;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * 主体上下文：记忆的项目归属解析。
 *
 * 对标 Python `memorycore/subject_context.py`（203 行，5 个公开函数）。
 * Java 迁移后该能力**整体缺失** —— 后果是 76% 的记忆 `project_path` 为空，
 * 无法按项目隔离/加权召回，且提取提示词丢失主体约束与标题自包含规则。
 *
 * 解析规则（命中即止，顺序跟随配置）：
 *   1. 路径精确匹配，或路径前缀匹配（仓库子目录）
 *   2. 项目名 / 别名大小写不敏感匹配
 * 无法确定时**返回 null，绝不猜测**。
 */
@Service
public class SubjectContextService {

    private static final Logger log = LoggerFactory.getLogger(SubjectContextService.class);

    /** 注入提取提示词的主体规则（对标 Python SUBJECT_PROMPT_INSTRUCTION） */
    public static final String SUBJECT_PROMPT_INSTRUCTION = """

            # Subject Context 规则（当前对话可能属于一个项目）

            - 输出 JSON 中每条 fact 必须附 "subject"（该事实归属的规范项目名）与 "entities"
              （实体名数组，可选）。subject 是主体判定的权威字段。
            - 若事实属于 Active Context 中的 project_name，则 title 必须以
              「<project_name> 」为前缀（如 "mcore 迭代31 …"），使事实脱离对话后仍能看出归属。
            - 若事实属于其他项目（对话常跨项目引用），不要强加本对话 project_name 前缀，
              而应在 subject 中写该事实真正归属的项目名。
            - 所有 fact 的 subject 字段都必须是具体项目名或空字符串，禁止泛化占位。
            """;

    /** 标题前缀分割符（对标 Python `re.split(r"[\s:：_\-—/\]\)\>】〕）]+", cleaned)`） */
    private static final Pattern TITLE_SPLIT =
            Pattern.compile("[\\s:：_\\-—/\\]\\)\\>】〕）]+");
    /** 标题开头需剥离的特殊括号 */
    private static final Pattern TITLE_LEAD_BRACKETS =
            Pattern.compile("^[\\[\\(\\<【〔（]+");

    private final ConfigFileStore configStore;

    public SubjectContextService(ConfigFileStore configStore) {
        this.configStore = configStore;
    }

    /** 读取生效的 subject_context 配置段；未启用时返回空 Map。 */
    public Map<String, Object> subjectConfig() {
        try {
            Map<String, Object> sc = configStore.section("subject_context");
            if (sc == null || sc.isEmpty()) {
                return Map.of();
            }
            Object enabled = sc.get("enabled");
            boolean on = enabled instanceof Boolean b ? b : Boolean.parseBoolean(String.valueOf(enabled));
            return on ? sc : Map.of();
        } catch (Exception e) {
            log.warn("读取 subject_context 配置失败: {}", e.getMessage());
            return Map.of();
        }
    }

    public boolean isEnabled() {
        return !subjectConfig().isEmpty();
    }

    /**
     * 自动发现 discovery_roots 下的 git 仓库作为项目主体。
     * 显式 `projects` 配置项在重名时优先。
     */
    public Map<String, Map<String, Object>> discoverProjects(Map<String, Object> sc) {
        if (sc == null || sc.isEmpty()) {
            sc = subjectConfig();
        }
        if (sc.isEmpty() || !asBool(sc.get("auto_discover"))) {
            return Map.of();
        }

        List<String> roots = asStringList(sc.get("discovery_roots"));
        if (roots.isEmpty()) {
            String envRoot = System.getenv("MCORE_PROJECTS_ROOT");
            roots = List.of(envRoot != null && !envRoot.isBlank()
                    ? envRoot
                    : Paths.get(System.getProperty("user.home"), "project").toString());
        }

        Map<String, Map<String, Object>> discovered = new LinkedHashMap<>();
        for (String r : roots) {
            Path base;
            try {
                base = expandPath(r);
            } catch (Exception e) {
                continue;
            }
            if (base == null || !Files.isDirectory(base)) {
                continue;
            }
            try (var stream = Files.list(base)) {
                List<Path> children = stream.sorted().toList();
                for (Path child : children) {
                    if (!Files.isDirectory(child)) {
                        continue;
                    }
                    if (Files.exists(child.resolve(".git"))) {
                        String name = child.getFileName().toString();
                        Map<String, Object> entry = new LinkedHashMap<>();
                        entry.put("name", name);
                        entry.put("aliases", List.of(name.toLowerCase(Locale.ROOT)));
                        entry.put("scope", "project");
                        entry.put("path", child.toString());
                        discovered.put(name.toLowerCase(Locale.ROOT), entry);
                    }
                }
            } catch (Exception e) {
                log.warn("扫描 discovery_root 失败: {} ({})", base, e.getMessage());
            }
        }
        return discovered;
    }

    /**
     * 解析 project_path / project_name 为规范项目。
     *
     * @return {"name","aliases","scope","path"}，无法确定时返回 null
     */
    public Map<String, Object> resolveProject(String projectPath, String projectName) {
        Map<String, Object> sc = subjectConfig();
        if (sc.isEmpty()) {
            return null;
        }
        List<Map<String, Object>> projects = asMapList(sc.get("projects"));
        Map<String, Map<String, Object>> discovered = discoverProjects(sc);

        String path = projectPath == null ? "" : projectPath.trim().replaceAll("/+$", "");
        String name = projectName == null ? "" : projectName.trim().toLowerCase(Locale.ROOT);

        Map<String, Object> explicit = matchEntry(projects, path, name);
        if (explicit != null) {
            return explicit;
        }
        if (!discovered.isEmpty()) {
            for (Map<String, Object> entry : discovered.values()) {
                String p = String.valueOf(entry.get("path")).replaceAll("/+$", "");
                if (!path.isEmpty() && !p.isEmpty()
                        && (path.equals(p) || path.startsWith(p + "/"))) {
                    Map<String, Object> copy = new LinkedHashMap<>(entry);
                    copy.put("path", p);
                    return copy;
                }
                Set<String> names = new LinkedHashSet<>();
                names.add(String.valueOf(entry.get("name")).toLowerCase(Locale.ROOT));
                names.addAll(asStringList(entry.get("aliases")));
                if (!name.isEmpty() && names.contains(name)) {
                    return new LinkedHashMap<>(entry);
                }
            }
        }
        return null;
    }

    private Map<String, Object> matchEntry(List<Map<String, Object>> projects, String path, String name) {
        for (Map<String, Object> entry : projects) {
            String projName = str(entry.get("name"));
            if (projName.isEmpty()) {
                continue;
            }
            List<String> aliases = new ArrayList<>();
            for (String a : asStringList(entry.get("aliases"))) {
                aliases.add(a.toLowerCase(Locale.ROOT));
            }
            Set<String> names = new LinkedHashSet<>();
            names.add(projName.toLowerCase(Locale.ROOT));
            names.addAll(aliases);

            if (!name.isEmpty() && names.contains(name)) {
                return build(projName, aliases, entry, pathOf(entry));
            }
            for (String p : asStringList(entry.get("paths"))) {
                String expanded = expandPathString(p).replaceAll("/+$", "");
                if (!path.isEmpty() && !expanded.isEmpty()
                        && (path.equals(expanded) || path.startsWith(expanded + "/"))) {
                    return build(projName, aliases, entry, expanded);
                }
            }
        }
        return null;
    }

    private Map<String, Object> build(String projName, List<String> aliases, Map<String, Object> entry, String path) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("name", projName);
        out.put("aliases", aliases);
        out.put("scope", str(entry.get("scope")).isEmpty() ? "project" : str(entry.get("scope")));
        out.put("path", path);
        return out;
    }

    private String pathOf(Map<String, Object> entry) {
        List<String> paths = asStringList(entry.get("paths"));
        return paths.isEmpty() ? "" : expandPathString(paths.get(0)).replaceAll("/+$", "");
    }

    /**
     * 从标题前缀推断项目归属（对标 Python `infer_subject_from_title`）。
     *
     * 先试首词（如 "mcore"、"MemoryCore"），再试前两词组合（如 "cpa-manager"）。
     */
    public Map<String, Object> inferSubjectFromTitle(String title) {
        if (title == null || title.trim().isEmpty()) {
            return null;
        }
        String cleaned = TITLE_LEAD_BRACKETS.matcher(title.trim()).replaceFirst("");
        List<String> tokens = new ArrayList<>();
        for (String t : TITLE_SPLIT.split(cleaned)) {
            if (!t.isEmpty()) {
                tokens.add(t);
            }
        }
        if (tokens.isEmpty()) {
            return null;
        }

        Map<String, Object> proj = resolveProject("", tokens.get(0).trim());
        if (proj != null) {
            return proj;
        }
        if (tokens.size() >= 2) {
            Map<String, Object> combo = resolveProject("", (tokens.get(0) + "-" + tokens.get(1)).trim());
            if (combo != null) {
                return combo;
            }
        }
        return null;
    }

    /** 注入提取提示词的 Active Context 块（仅在项目名已知时非空） */
    public String activeContextBlock(String projectName, String projectPath, String scope) {
        if (projectName == null || projectName.isBlank()) {
            return "";
        }
        StringBuilder sb = new StringBuilder("## Active Context（当前对话主体）\n");
        sb.append("- project_name: ").append(projectName).append("\n");
        if (projectPath != null && !projectPath.isBlank()) {
            sb.append("- project_path: ").append(projectPath).append("\n");
        }
        sb.append("- scope: ").append(scope == null || scope.isBlank() ? "global" : scope);
        return sb.toString();
    }

    // ---------- 工具方法 ----------

    private String expandPathString(String raw) {
        try {
            Path p = expandPath(raw);
            return p == null ? "" : p.toString();
        } catch (Exception e) {
            return raw == null ? "" : raw;
        }
    }

    /** 展开 `~` 与 `$VAR`（可移植配置在解析期展开，避免硬编码绝对路径） */
    private Path expandPath(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        String s = raw.trim();
        if (s.startsWith("~")) {
            s = System.getProperty("user.home") + s.substring(1);
        }
        java.util.regex.Matcher m = Pattern.compile("\\$\\{?([A-Za-z_][A-Za-z0-9_]*)\\}?").matcher(s);
        StringBuilder sb = new StringBuilder();
        while (m.find()) {
            String v = System.getenv(m.group(1));
            m.appendReplacement(sb, v == null ? "" : java.util.regex.Matcher.quoteReplacement(v));
        }
        m.appendTail(sb);
        return Paths.get(sb.toString());
    }

    private boolean asBool(Object v) {
        if (v instanceof Boolean b) {
            return b;
        }
        return v != null && Boolean.parseBoolean(String.valueOf(v));
    }

    private String str(Object v) {
        return v == null ? "" : String.valueOf(v).trim();
    }

    @SuppressWarnings("unchecked")
    private List<String> asStringList(Object v) {
        List<String> out = new ArrayList<>();
        if (v instanceof List<?> list) {
            for (Object o : list) {
                if (o != null) {
                    out.add(String.valueOf(o));
                }
            }
        }
        return out;
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> asMapList(Object v) {
        List<Map<String, Object>> out = new ArrayList<>();
        if (v instanceof List<?> list) {
            for (Object o : list) {
                if (o instanceof Map<?, ?> m) {
                    Map<String, Object> cast = new LinkedHashMap<>();
                    m.forEach((k, val) -> cast.put(String.valueOf(k), val));
                    out.add(cast);
                }
            }
        }
        return out;
    }
}
