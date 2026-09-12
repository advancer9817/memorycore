package org.mcore.server.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.mcore.common.result.ErrorCode;
import org.mcore.common.result.Result;
import org.mcore.tenancy.routing.TenantContextHolder;
import org.mcore.tenancy.security.TenantApiKeyService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Optional;

/**
 * 租户上下文解析与调用方身份鉴权拦截器
 * <p>
 * 授权模型：
 * <ul>
 *   <li>{@code default} 共享租户 —— 保持向后兼容，本地 Agent 钩子无需携带任何凭证；</li>
 *   <li>其余租户 —— 必须携带有效 API Key（{@code X-API-Key} 头或 {@code Authorization: Bearer}），
 *       且密钥必须与请求声明的租户一致，否则 403。</li>
 * </ul>
 * 阿里规约强约束：ThreadLocal 必须在 finally 中强制清理，防范线程复用导致的租户上下文串号。
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class TenantAuthFilter extends OncePerRequestFilter {
    private static final Logger log = LoggerFactory.getLogger(TenantAuthFilter.class);

    /** 无需鉴权的公开探活路径 */
    private static final String[] PUBLIC_PATHS = {"/health", "/actuator", "/error"};

    /** 租户管理面路径前缀（开辟/销毁/枚举/密钥），属高危运维操作 */
    private static final String ADMIN_PREFIX = "/api/v1/tenant";

    /** 反向代理注入的请求头，出现即说明经由隧道转发，不可信任为本地直连 */
    private static final String[] PROXY_HEADERS = {
            "X-Forwarded-For", "X-Real-IP", "CF-Connecting-IP", "True-Client-IP"
    };

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final TenantApiKeyService apiKeyService;

    @Value("${mcore.security.enabled:true}")
    private boolean securityEnabled;

    @Value("${mcore.security.default-tenant:default}")
    private String defaultTenant;

    public TenantAuthFilter(TenantApiKeyService apiKeyService) {
        this.apiKeyService = apiKeyService;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        try {
            // 1. 解析请求声明的目标租户
            String requestedTenant = request.getHeader("X-Tenant-Id");
            if (requestedTenant == null || requestedTenant.isBlank()) {
                requestedTenant = defaultTenant;
            }
            requestedTenant = requestedTenant.trim();

            // 2. 授权校验
            if (securityEnabled && !isPublicPath(request)) {
                boolean isAdminPath = isAdminPath(request);
                boolean isNonDefaultTenant = !defaultTenant.equals(requestedTenant);

                // 2.1 管理面：仅限本机直连运维通道，隧道来的外部请求一律需有效密钥
                if (isAdminPath && !isDirectLocalRequest(request)) {
                    Optional<TenantApiKeyService.TenantPrincipal> adminPrincipal =
                            apiKeyService.authenticate(extractApiKey(request));
                    if (adminPrincipal.isEmpty()) {
                        log.warn("拒绝外部访问租户管理面: path={} remote={}", request.getRequestURI(), request.getRemoteAddr());
                        writeError(response, ErrorCode.CLIENT_UNAUTHORIZED, "租户管理接口仅限本机运维访问，或需提供有效 API Key");
                        return;
                    }
                    // 修复：此前只校验"key 有效"，不比对 key 归属与操作目标租户，
                    // 导致持有 A 租户任意 key 即可跨租户开辟/销毁数据库、签发/吊销他人密钥。
                    String targetTenant = extractAdminTargetTenant(request);
                    String denyReason = authorizeAdminTarget(adminPrincipal.get(), targetTenant);
                    if (denyReason != null) {
                        log.warn("拒绝越权租户管理操作: key归属={} 目标租户={} path={} 原因={}",
                                adminPrincipal.get().tenantId(), targetTenant, request.getRequestURI(), denyReason);
                        writeError(response, ErrorCode.CLIENT_FORBIDDEN, denyReason);
                        return;
                    }
                    request.setAttribute("tenant_scopes", adminPrincipal.get().scopes());
                    request.setAttribute("api_key_id", adminPrincipal.get().keyId());
                    request.setAttribute("admin_target_tenant", targetTenant);
                }

                // 2.2 数据面：非 default 租户必须持有效且归属一致的密钥
                if (!isAdminPath && isNonDefaultTenant) {
                    Optional<TenantApiKeyService.TenantPrincipal> principal =
                            apiKeyService.authenticate(extractApiKey(request));
                    if (principal.isEmpty()) {
                        log.warn("拒绝未授权租户访问: tenant={} remote={} path={}",
                                requestedTenant, request.getRemoteAddr(), request.getRequestURI());
                        writeError(response, ErrorCode.CLIENT_UNAUTHORIZED,
                                "访问租户 [" + requestedTenant + "] 需提供有效 API Key");
                        return;
                    }
                    if (!requestedTenant.equals(principal.get().tenantId())) {
                        log.warn("拒绝跨租户越权: 密钥归属={} 请求目标={} path={}",
                                principal.get().tenantId(), requestedTenant, request.getRequestURI());
                        writeError(response, ErrorCode.CLIENT_FORBIDDEN,
                                "该密钥无权访问租户 [" + requestedTenant + "]");
                        return;
                    }
                    request.setAttribute("tenant_scopes", principal.get().scopes());
                    request.setAttribute("api_key_id", principal.get().keyId());
                }
            }

            // 3. 授权通过后才绑定租户上下文
            TenantContextHolder.setTenantId(requestedTenant);

            // 4. 推断调用方 Agent 身份（仅用于审计标注，不参与鉴权）
            request.setAttribute("caller_agent",
                    inferCallerAgent(request.getHeader("User-Agent"), request.getHeader("X-Client-Info")));

            filterChain.doFilter(request, response);
        } finally {
            // 强制清理 ThreadLocal，防范线程复用污染
            TenantContextHolder.remove();
        }
    }

    /**
     * 依次尝试 X-API-Key 头与标准 Authorization: Bearer 头
     */
    private String extractApiKey(HttpServletRequest request) {
        String direct = request.getHeader("X-API-Key");
        if (direct != null && !direct.isBlank()) {
            return direct.trim();
        }
        String auth = request.getHeader("Authorization");
        if (auth != null && auth.regionMatches(true, 0, "Bearer ", 0, 7)) {
            return auth.substring(7).trim();
        }
        return null;
    }

    private boolean isAdminPath(HttpServletRequest request) {
        String path = request.getRequestURI();
        return path != null && path.startsWith(ADMIN_PREFIX);
    }

    /**
     * 判定是否为「本机直连」请求：来源为回环地址，且不含任何反向代理注入头。
     * <p>
     * 注意：Cloudflare Tunnel 回源到 127.0.0.1，仅凭 remoteAddr 无法区分内外网，
     * 因此必须叠加代理头检测，否则隧道流量会被误判为本地运维通道。
     */
    private boolean isDirectLocalRequest(HttpServletRequest request) {
        for (String header : PROXY_HEADERS) {
            String value = request.getHeader(header);
            if (value != null && !value.isBlank()) {
                return false;
            }
        }
        String remote = request.getRemoteAddr();
        return "127.0.0.1".equals(remote)
                || "::1".equals(remote)
                || "0:0:0:0:0:0:0:1".equals(remote);
    }

    /**
     * 从管理面请求中解析操作目标租户。
     * - `/api/v1/tenant/provision?tenantId=X` → X
     * - `/api/v1/tenant/{id}` 或 `/api/v1/tenant/{id}/keys...` → id
     * - `/api/v1/tenant/list`（枚举全部租户，无单一目标）→ null
     */
    private String extractAdminTargetTenant(HttpServletRequest request) {
        String path = request.getRequestURI();
        if (path == null) {
            return null;
        }
        // provision 的目标租户来自查询参数
        String paramTenant = request.getParameter("tenantId");
        if (paramTenant != null && !paramTenant.isBlank()) {
            return paramTenant.trim();
        }
        String prefix = ADMIN_PREFIX + "/";
        if (!path.startsWith(prefix)) {
            return null;
        }
        String rest = path.substring(prefix.length());
        if (rest.isBlank()) {
            return null;
        }
        int slash = rest.indexOf('/');
        String first = slash >= 0 ? rest.substring(0, slash) : rest;
        // list 是全局枚举，非针对某一租户
        if ("list".equals(first) || "provision".equals(first)) {
            return null;
        }
        return first;
    }

    /**
     * 管理面授权判定。返回 null 表示允许，否则返回拒绝原因。
     *
     * 规则：
     * - 目标租户为空（如 /tenant/list 全局枚举）→ 需 `admin` scope
     * - key 归属 == 目标租户 → 允许（自助管理自己的租户）
     * - 否则需 `admin` scope
     */
    private String authorizeAdminTarget(TenantApiKeyService.TenantPrincipal principal, String targetTenant) {
        java.util.Set<String> scopes = principal.scopes() == null ? java.util.Set.of() : principal.scopes();
        boolean isAdmin = scopes.contains("admin") || scopes.contains("*");

        if (targetTenant == null || targetTenant.isBlank()) {
            if (isAdmin) {
                return null;
            }
            return "枚举租户列表需要 admin 权限的 API Key";
        }
        if (targetTenant.equals(principal.tenantId())) {
            return null;
        }
        if (isAdmin) {
            return null;
        }
        return "该密钥归属租户 [" + principal.tenantId() + "]，无权管理租户 [" + targetTenant + "]";
    }

    private boolean isPublicPath(HttpServletRequest request) {
        String path = request.getRequestURI();
        if (path == null) {
            return false;
        }
        for (String pub : PUBLIC_PATHS) {
            if (path.equals(pub) || path.startsWith(pub + "/")) {
                return true;
            }
        }
        return false;
    }

    /**
     * 按 ErrorCode 映射 HTTP 状态。
     * 修复：此前恒定 401，即使传入 CLIENT_FORBIDDEN（跨租户越权），
     * 与 `docs/mcore-multi-tenant-security-model.md` 宣称的 403 语义不符，
     * 调用方无法区分"未携带凭证"与"越权"。
     */
    private void writeError(HttpServletResponse response, ErrorCode errorCode, String message) throws IOException {
        response.setStatus(httpStatusFor(errorCode));
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        Result<Void> body = Result.failure(errorCode.getCode(), message);
        response.getWriter().write(MAPPER.writeValueAsString(body));
    }

    private int httpStatusFor(ErrorCode errorCode) {
        if (errorCode == null || errorCode.getCode() == null) {
            return HttpServletResponse.SC_UNAUTHORIZED;
        }
        String name = errorCode.name();
        if (name.contains("FORBIDDEN")) {
            return HttpServletResponse.SC_FORBIDDEN;
        }
        if (name.contains("PARAM")) {
            return HttpServletResponse.SC_BAD_REQUEST;
        }
        if (name.contains("NOT_FOUND")) {
            return HttpServletResponse.SC_NOT_FOUND;
        }
        return HttpServletResponse.SC_UNAUTHORIZED;
    }

    private String inferCallerAgent(String userAgent, String clientInfo) {
        String combined = ((userAgent != null ? userAgent : "") + " " + (clientInfo != null ? clientInfo : "")).toLowerCase();
        if (combined.contains("claude")) return "claude";
        if (combined.contains("hermes")) return "hermes";
        if (combined.contains("codex")) return "codex";
        if (combined.contains("opencode")) return "opencode";
        return "generic";
    }
}
