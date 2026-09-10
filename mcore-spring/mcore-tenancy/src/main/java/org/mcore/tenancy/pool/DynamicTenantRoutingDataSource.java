package org.mcore.tenancy.pool;

import com.github.benmanes.caffeine.cache.Caffeine;
import com.github.benmanes.caffeine.cache.LoadingCache;
import com.github.benmanes.caffeine.cache.RemovalCause;
import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import org.mcore.common.exception.McoreSystemException;
import org.mcore.common.result.ErrorCode;
import org.mcore.tenancy.routing.TenantContextHolder;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.datasource.lookup.AbstractRoutingDataSource;

import javax.sql.DataSource;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 动态多租户路由数据源
 * 基于 Caffeine LRU 缓存与 HikariCP 微型租户连接池（min=1, max=3）
 */
public class DynamicTenantRoutingDataSource extends AbstractRoutingDataSource {
    private static final Logger log = LoggerFactory.getLogger(DynamicTenantRoutingDataSource.class);

    private static final int MAX_ACTIVE_POOLS = 40;
    private final AtomicInteger activePoolCount = new AtomicInteger(0);

    private final String host;
    private final int port;
    private final String username;
    private final String password;
    private final LoadingCache<String, HikariDataSource> tenantPoolCache;

    public DynamicTenantRoutingDataSource(String host, int port, String username, String password, DataSource defaultDataSource) {
        this.host = host;
        this.port = port;
        this.username = username;
        this.password = password;
        setDefaultTargetDataSource(defaultDataSource);
        setTargetDataSources(java.util.Collections.singletonMap("default", defaultDataSource));
        afterPropertiesSet();

        this.tenantPoolCache = Caffeine.newBuilder()
                .maximumSize(MAX_ACTIVE_POOLS)
                .expireAfterAccess(Duration.ofMinutes(15))
                .removalListener((String tenantId, HikariDataSource ds, RemovalCause cause) -> {
                    if (ds != null && !ds.isClosed()) {
                        log.info("LRU 回收租户连接池 [{}], 原因: {}, 释放底层物理连接", tenantId, cause);
                        ds.close();
                        activePoolCount.decrementAndGet();
                    }
                })
                .build(this::createTenantDataSource);
    }

    @Override
    protected Object determineCurrentLookupKey() {
        return TenantContextHolder.getTenantId();
    }

    @Override
    protected DataSource determineTargetDataSource() {
        String tenantId = (String) determineCurrentLookupKey();
        if ("default".equalsIgnoreCase(tenantId) || "system".equalsIgnoreCase(tenantId)) {
            return (DataSource) getResolvedDefaultDataSource();
        }
        return tenantPoolCache.get(tenantId);
    }

    private HikariDataSource createTenantDataSource(String tenantId) {
        if (activePoolCount.get() >= MAX_ACTIVE_POOLS) {
            log.warn("当前活跃租户池达到上限 ({}), 触发主动 LRU 驱逐清理", MAX_ACTIVE_POOLS);
            tenantPoolCache.cleanUp();
        }

        String cleanId = tenantId.replace("-", "_").toLowerCase();
        String dbName = "mcore_u_" + cleanId;
        String jdbcUrl = String.format("jdbc:postgresql://%s:%d/%s?sslmode=prefer&ApplicationName=mcore_%s",
                host, port, dbName, cleanId);

        try {
            HikariConfig config = new HikariConfig();
            config.setJdbcUrl(jdbcUrl);
            config.setUsername(username);
            config.setPassword(password);
            config.setPoolName("Hikari-Tenant-" + cleanId);
            
            // 阿里规范微型连接池参数
            config.setMinimumIdle(1);
            config.setMaximumPoolSize(3);
            config.setIdleTimeout(300000);
            config.setConnectionTimeout(8000);
            config.setMaxLifetime(1800000);
            config.setValidationTimeout(3000);

            HikariDataSource ds = new HikariDataSource(config);
            int currentCount = activePoolCount.incrementAndGet();
            log.info("成功为租户 [{}] 创建微型连接池 (数据库: {}, 当前活跃池数: {})", tenantId, dbName, currentCount);
            return ds;
        } catch (Exception e) {
            log.error("构建租户连接池 [{}] 失败: {}", tenantId, e.getMessage(), e);
            throw new McoreSystemException(ErrorCode.SYSTEM_ERROR, e);
        }
    }
}
