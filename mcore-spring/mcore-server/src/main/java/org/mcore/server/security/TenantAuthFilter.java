package org.mcore.server.security;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.mcore.tenancy.routing.TenantContextHolder;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * 租户上下文与调用方 Agent 身份解析拦截器
 * 阿里规约强约束：在 finally 中强制调用 remove() 清理 ThreadLocal
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class TenantAuthFilter extends OncePerRequestFilter {

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        try {
            // 1. 提取租户标识 (优先 Header -> 默认 "default")
            String tenantId = request.getHeader("X-Tenant-Id");
            if (tenantId == null || tenantId.isBlank()) {
                tenantId = "default";
            }
            TenantContextHolder.setTenantId(tenantId);

            // 2. 推断调用方 Agent 身份
            String userAgent = request.getHeader("User-Agent");
            String clientInfo = request.getHeader("X-Client-Info");
            String callerAgent = inferCallerAgent(userAgent, clientInfo);
            request.setAttribute("caller_agent", callerAgent);

            filterChain.doFilter(request, response);
        } finally {
            // 强制清理 ThreadLocal，防范线程复用污染
            TenantContextHolder.remove();
        }
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
