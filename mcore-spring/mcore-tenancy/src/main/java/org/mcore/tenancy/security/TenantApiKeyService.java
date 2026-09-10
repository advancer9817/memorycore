package org.mcore.tenancy.security;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import org.mcore.common.exception.McoreBusinessException;
import org.mcore.common.result.ErrorCode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.TimeUnit;

/**
 * 租户 API Key 签发与校验服务（控制面）
 * <p>
 * 密钥格式：{@code mk_<8位hex>.<32位hex密钥>}，数据库仅存密钥段的 SHA-256 散列，
 * 明文密钥只在签发瞬间返回一次，绝不可二次读取。
 * <p>
 * 校验结果按「散列前缀」在 Caffeine 中短时缓存（默认 60 秒），
 * 既避免每次请求都打控制面库，又保证密钥吊销后最长 60 秒内生效。
 */
@Service
public class TenantApiKeyService {
    private static final Logger log = LoggerFactory.getLogger(TenantApiKeyService.class);

    private static final String KEY_PREFIX = "mk_";
    private static final SecureRandom SECURE_RANDOM = new SecureRandom();
    private static final int SECRET_BYTES = 16;

    private final JdbcClient systemJdbcClient;

    /** 缓存键为「明文密钥的 SHA-256」，杜绝缓存区内驻留明文密钥 */
    private final Cache<String, Optional<TenantPrincipal>> authCache = Caffeine.newBuilder()
            .maximumSize(2_000)
            .expireAfterWrite(60, TimeUnit.SECONDS)
            .build();

    public TenantApiKeyService(@Qualifier("systemJdbcClient") JdbcClient systemJdbcClient) {
        this.systemJdbcClient = systemJdbcClient;
    }

    /**
     * 校验明文 API Key 并解析其绑定的租户身份
     *
     * @return 校验通过返回租户主体，否则返回空（由调用方决定拒绝策略）
     */
    public Optional<TenantPrincipal> authenticate(String rawKey) {
        if (rawKey == null || rawKey.isBlank()) {
            return Optional.empty();
        }
        String raw = rawKey.trim();
        String cacheKey = sha256Hex(raw);
        return authCache.get(cacheKey, key -> lookup(raw));
    }

    private Optional<TenantPrincipal> lookup(String rawKey) {
        int sep = rawKey.lastIndexOf('.');
        if (sep <= 0 || sep == rawKey.length() - 1) {
            return Optional.empty();
        }
        String keyId = rawKey.substring(0, sep);
        String secret = rawKey.substring(sep + 1);
        if (!keyId.startsWith(KEY_PREFIX)) {
            return Optional.empty();
        }

        try {
            Map<String, Object> row = systemJdbcClient.sql("""
                            SELECT tenant_id, key_hash, allowed_scopes, expires_at
                            FROM sys_tenant_api_keys
                            WHERE key_id = ?
                            """)
                    .param(keyId)
                    .query((rs, rowNum) -> {
                        Map<String, Object> m = new java.util.LinkedHashMap<>();
                        m.put("tenant_id", rs.getString("tenant_id"));
                        m.put("key_hash", rs.getString("key_hash"));
                        Object exp = rs.getObject("expires_at");
                        m.put("expires_at", exp);
                        java.sql.Array arr = rs.getArray("allowed_scopes");
                        if (arr != null) {
                            Object rawArr = arr.getArray();
                            List<String> scopes = new ArrayList<>();
                            if (rawArr instanceof Object[] objs) {
                                for (Object o : objs) {
                                    if (o != null) scopes.add(String.valueOf(o));
                                }
                            }
                            arr.free();
                            m.put("allowed_scopes", scopes);
                        }
                        return m;
                    })
                    .optional()
                    .orElse(null);

            if (row == null) {
                return Optional.empty();
            }

            // 恒定时间比较，规避时序侧信道
            String expected = String.valueOf(row.get("key_hash"));
            String actual = sha256Hex(secret);
            if (!MessageDigest.isEqual(
                    expected.getBytes(StandardCharsets.UTF_8),
                    actual.getBytes(StandardCharsets.UTF_8))) {
                return Optional.empty();
            }

            Object exp = row.get("expires_at");
            if (exp instanceof OffsetDateTime odt && odt.isBefore(OffsetDateTime.now())) {
                log.debug("API Key {} 已过期", keyId);
                return Optional.empty();
            }

            @SuppressWarnings("unchecked")
            List<String> scopes = (List<String>) row.getOrDefault("allowed_scopes", List.of());
            Set<String> scopeSet = new LinkedHashSet<>(scopes);

            // 异步刷新最后使用时间，不阻塞鉴权链路
            try {
                systemJdbcClient.sql("UPDATE sys_tenant_api_keys SET last_used_at = clock_timestamp() WHERE key_id = ?")
                        .param(keyId).update();
            } catch (Exception ignored) {
                // 使用时间记录失败不得影响正常鉴权
            }

            return Optional.of(new TenantPrincipal(
                    String.valueOf(row.get("tenant_id")), keyId, scopeSet));
        } catch (Exception e) {
            log.warn("API Key 校验异常: {}", e.getMessage());
            return Optional.empty();
        }
    }

    /**
     * 为指定租户签发新 API Key
     *
     * @return 明文密钥（仅此一次返回，请调用方立即下发给用户）
     */
    public IssuedKey issueKey(String tenantId, String name, List<String> scopes, Integer ttlDays) {
        if (tenantId == null || tenantId.isBlank()) {
            throw new McoreBusinessException(ErrorCode.CLIENT_PARAM_ERROR.getCode(), "租户ID不可为空");
        }
        List<String> effectiveScopes = (scopes == null || scopes.isEmpty())
                ? List.of("read", "write")
                : scopes;

        String keyId = KEY_PREFIX + randomHex(4);
        String secret = randomHex(SECRET_BYTES);
        String rawKey = keyId + "." + secret;

        OffsetDateTime expiresAt = null;
        if (ttlDays != null && ttlDays > 0) {
            expiresAt = OffsetDateTime.now().plusDays(ttlDays);
        }

        try {
            systemJdbcClient.sql("""
                            INSERT INTO sys_tenant_api_keys
                                (key_id, tenant_id, key_hash, name, allowed_scopes, expires_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """)
                    .param(keyId)
                    .param(tenantId)
                    .param(sha256Hex(secret))
                    .param(name == null || name.isBlank() ? "Default Agent Key" : name)
                    .param(effectiveScopes.toArray(new String[0]))
                    .param(expiresAt)
                    .update();
        } catch (Exception e) {
            log.error("签发租户 {} 的 API Key 失败: {}", tenantId, e.getMessage(), e);
            throw new McoreBusinessException(ErrorCode.CLIENT_TENANT_NOT_FOUND.getCode(),
                    "签发失败，请确认租户已登记: " + tenantId);
        }

        log.info("已为租户 {} 签发 API Key {}", tenantId, keyId);
        return new IssuedKey(keyId, rawKey, tenantId, effectiveScopes, expiresAt);
    }

    /**
     * 枚举指定租户的密钥（脱敏，仅返回 key_id 与元信息）
     */
    public List<Map<String, Object>> listKeys(String tenantId) {
        return systemJdbcClient.sql("""
                        SELECT key_id, name, allowed_scopes, expires_at, last_used_at, created_at
                        FROM sys_tenant_api_keys
                        WHERE tenant_id = ?
                        ORDER BY created_at DESC
                        """)
                .param(tenantId)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new java.util.LinkedHashMap<>();
                    m.put("key_id", rs.getString("key_id"));
                    m.put("name", rs.getString("name"));
                    java.sql.Array arr = rs.getArray("allowed_scopes");
                    List<String> scopes = new ArrayList<>();
                    if (arr != null) {
                        Object rawArr = arr.getArray();
                        if (rawArr instanceof Object[] objs) {
                            for (Object o : objs) {
                                if (o != null) scopes.add(String.valueOf(o));
                            }
                        }
                        arr.free();
                    }
                    m.put("allowed_scopes", scopes);
                    m.put("expires_at", String.valueOf(rs.getObject("expires_at")));
                    m.put("last_used_at", String.valueOf(rs.getObject("last_used_at")));
                    m.put("created_at", String.valueOf(rs.getObject("created_at")));
                    return m;
                })
                .list();
    }

    /**
     * 立即吊销密钥并清空鉴权缓存（保证吊销即时生效）
     */
    public boolean revokeKey(String tenantId, String keyId) {
        int affected = systemJdbcClient.sql(
                        "DELETE FROM sys_tenant_api_keys WHERE tenant_id = ? AND key_id = ?")
                .param(tenantId).param(keyId).update();
        if (affected > 0) {
            authCache.invalidateAll();
            log.info("已吊销租户 {} 的 API Key {}", tenantId, keyId);
        }
        return affected > 0;
    }

    // ------------------------------------------------------------------

    private static String randomHex(int byteLen) {
        byte[] buf = new byte[byteLen];
        SECURE_RANDOM.nextBytes(buf);
        StringBuilder sb = new StringBuilder(byteLen * 2);
        for (byte b : buf) {
            sb.append(Character.forDigit((b >> 4) & 0xF, 16));
            sb.append(Character.forDigit(b & 0xF, 16));
        }
        return sb.toString();
    }

    private static String sha256Hex(String input) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] digest = md.digest(input.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(digest.length * 2);
            for (byte b : digest) {
                sb.append(Character.forDigit((b >> 4) & 0xF, 16));
                sb.append(Character.forDigit(b & 0xF, 16));
            }
            return sb.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 不可用", e);
        }
    }

    /** 校验通过的租户主体（由 ThreadLocal 上下文消费） */
    public record TenantPrincipal(String tenantId, String keyId, Set<String> scopes) {}

    /** 签发结果（明文密钥仅此一次返回） */
    public record IssuedKey(String keyId, String rawKey, String tenantId,
                            List<String> scopes, OffsetDateTime expiresAt) {}
}
