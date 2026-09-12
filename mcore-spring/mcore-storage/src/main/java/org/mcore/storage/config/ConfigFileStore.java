package org.mcore.storage.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.yaml.snakeyaml.DumperOptions;
import org.yaml.snakeyaml.Yaml;

import java.io.IOException;
import java.io.Reader;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermission;
import java.util.*;

/**
 * 配置文件的唯一事实源（存储层）。
 *
 * 为什么存在：提取/嵌入等运行时服务过去只用 @Value 读取 application.yml，配置在进程启动时即被冻结，
 * 导致前端设置页的修改「看着保存成功、实际不生效」。此组件提供运行时可读的配置，
 * 使设置改动在下次调用时即刻生效，无需重启。
 *
 * 性能：按文件 mtime + size 做缓存，未变更时零解析开销。
 */
@Component
public class ConfigFileStore {

    private final Path configPath;
    private final Yaml yaml;
    private final Object lock = new Object();

    private volatile Map<String, Object> cache;
    private volatile long cacheStamp = -1L;

    public ConfigFileStore(@Value("${mcore.config-path:../config.yaml}") String path) {
        this.configPath = Paths.get(path).toAbsolutePath().normalize();
        DumperOptions opts = new DumperOptions();
        opts.setDefaultFlowStyle(DumperOptions.FlowStyle.BLOCK);
        opts.setPrettyFlow(true);
        opts.setIndent(2);
        opts.setAllowUnicode(true);
        opts.setWidth(4096);
        this.yaml = new Yaml(opts);
    }

    public Path getConfigPath() {
        return configPath;
    }

    /** 读取原始配置（带 mtime 缓存） */
    @SuppressWarnings("unchecked")
    public Map<String, Object> raw() {
        synchronized (lock) {
            try {
                if (!Files.exists(configPath)) {
                    return new LinkedHashMap<>();
                }
                long stamp = Files.getLastModifiedTime(configPath).toMillis() * 31 + Files.size(configPath);
                Map<String, Object> cached = cache;
                if (cached != null && stamp == cacheStamp) {
                    return cached;
                }
                try (Reader r = Files.newBufferedReader(configPath, StandardCharsets.UTF_8)) {
                    Object loaded = yaml.load(r);
                    Map<String, Object> res = loaded instanceof Map
                            ? new LinkedHashMap<>((Map<String, Object>) loaded)
                            : new LinkedHashMap<>();
                    cache = res;
                    cacheStamp = stamp;
                    return res;
                }
            } catch (IOException e) {
                throw new IllegalStateException("读取配置文件失败: " + configPath + " - " + e.getMessage(), e);
            }
        }
    }

    /** 覆盖写入配置（同目录临时文件 + 原子 move） */
    public void write(Map<String, Object> cfg) {
        synchronized (lock) {
            try {
                Path dir = configPath.getParent();
                if (dir != null && !Files.exists(dir)) {
                    Files.createDirectories(dir);
                }
                Path tmp = Files.createTempFile(dir, ".config-", ".yaml.tmp");
                try (Writer w = Files.newBufferedWriter(tmp, StandardCharsets.UTF_8)) {
                    yaml.dump(cfg, w);
                }
                enforcePermissions(tmp);
                try {
                    Files.move(tmp, configPath, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
                } catch (AtomicMoveNotSupportedException e) {
                    Files.move(tmp, configPath, StandardCopyOption.REPLACE_EXISTING);
                }
                enforcePermissions(configPath);
                cache = null;
                cacheStamp = -1L;
            } catch (IOException e) {
                throw new IllegalStateException("写入配置文件失败: " + configPath + " - " + e.getMessage(), e);
            }
        }
    }

    // ==================== 运行时读取（供提取/嵌入服务） ====================

    /** 提取模型配置：base_url / api_key / model / temperature / max_tokens / timeout */
    public Map<String, Object> extractionSettings() {
        return section("extraction");
    }

    /** 嵌入模型配置：provider / model / api_key / ollama_url / api_url / dim / timeout */
    public Map<String, Object> embeddingSettings() {
        return section("embedding");
    }

    public Map<String, Object> section(String name) {
        Object v = raw().get(name);
        if (v instanceof Map) {
            @SuppressWarnings("unchecked")
            Map<String, Object> m = new LinkedHashMap<>((Map<String, Object>) v);
            return m;
        }
        return new LinkedHashMap<>();
    }

    public String str(Map<String, Object> m, String key, String fallback) {
        Object v = m.get(key);
        if (v == null) {
            return fallback;
        }
        String s = String.valueOf(v).trim();
        return s.isEmpty() ? fallback : s;
    }

    public int intVal(Map<String, Object> m, String key, int fallback) {
        Object v = m.get(key);
        if (v == null) {
            return fallback;
        }
        try {
            if (v instanceof Number) {
                return ((Number) v).intValue();
            }
            String s = String.valueOf(v).trim();
            return s.isEmpty() ? fallback : (int) Double.parseDouble(s);
        } catch (NumberFormatException e) {
            return fallback;
        }
    }

    public double doubleVal(Map<String, Object> m, String key, double fallback) {
        Object v = m.get(key);
        if (v == null) {
            return fallback;
        }
        try {
            if (v instanceof Number) {
                return ((Number) v).doubleValue();
            }
            String s = String.valueOf(v).trim();
            return s.isEmpty() ? fallback : Double.parseDouble(s);
        } catch (NumberFormatException e) {
            return fallback;
        }
    }

    private void enforcePermissions(Path p) {
        try {
            Set<PosixFilePermission> perms = new HashSet<>(Arrays.asList(
                    PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE));
            Files.setPosixFilePermissions(p, perms);
        } catch (Exception ignored) {
            // 非 POSIX 文件系统跳过
        }
    }
}
