package org.mcore.server.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.util.Arrays;

/**
 * 跨域策略。
 *
 * 修复：此前为 `allowedOriginPatterns("*")` 全开放 —— 任意网页来源可对
 * `/api/v1/**`、`/mcp` 发起跨域请求并读取响应（无凭证模式），配合默认租户免鉴权，
 * 可从访客浏览器直接读改默认租户记忆。
 *
 * 现收敛为显式来源白名单，默认仅本地 UI（18318）与回环，可通过
 * `MCORE_CORS_ORIGINS` 追加（逗号分隔）。
 */
@Configuration
public class CorsConfig implements WebMvcConfigurer {

    @Value("${mcore.cors.allowed-origins:http://127.0.0.1:18318,http://localhost:18318,http://127.0.0.1:38318,http://localhost:38318}")
    private String allowedOrigins;

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        String[] origins = Arrays.stream(allowedOrigins.split(","))
                .map(String::trim)
                .filter(s -> !s.isEmpty())
                .toArray(String[]::new);

        registry.addMapping("/**")
                .allowedOrigins(origins)
                .allowedMethods("GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH")
                .allowedHeaders("*")
                .exposedHeaders("X-Tenant-Id")
                .allowCredentials(false)
                .maxAge(3600);
    }
}
