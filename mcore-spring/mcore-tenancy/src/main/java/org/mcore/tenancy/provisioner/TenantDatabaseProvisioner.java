package org.mcore.tenancy.provisioner;

import org.mcore.common.exception.McoreBusinessException;
import org.mcore.common.exception.McoreSystemException;
import org.mcore.common.result.ErrorCode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Component;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.Statement;
import java.util.regex.Pattern;

/**
 * 租户物理数据库生命周期开辟与销毁引擎
 */
@Component
public class TenantDatabaseProvisioner {
    private static final Logger log = LoggerFactory.getLogger(TenantDatabaseProvisioner.class);
    private static final Pattern SAFE_TENANT_ID_PATTERN = Pattern.compile("^[a-zA-Z0-9_-]{1,32}$");

    private final DataSource systemDataSource;

    public TenantDatabaseProvisioner(@Qualifier("defaultDataSource") DataSource systemDataSource) {
        this.systemDataSource = systemDataSource;
    }

    /**
     * 基于 template_mcore 毫秒级物理写时复制（COW）开辟新租户数据库
     */
    public void provisionTenantDatabase(String tenantId, String dbUser) {
        if (tenantId == null || !SAFE_TENANT_ID_PATTERN.matcher(tenantId).matches()) {
            throw new McoreBusinessException(ErrorCode.CLIENT_PARAM_ERROR.getCode(), "非法租户ID标识: " + tenantId);
        }

        String cleanId = tenantId.replace("-", "_").toLowerCase();
        String dbName = "mcore_u_" + cleanId;

        // 必须采用独立非事务自动提交连接执行 DDL
        try (Connection conn = systemDataSource.getConnection()) {
            conn.setAutoCommit(true);
            try (Statement stmt = conn.createStatement()) {
                log.info("开始物理克隆租户数据库: {} (模板源: template_mcore)", dbName);
                long start = System.currentTimeMillis();

                String sql = String.format(
                    "CREATE DATABASE %s WITH TEMPLATE template_mcore OWNER %s",
                    dbName, dbUser
                );
                stmt.execute(sql);

                long duration = System.currentTimeMillis() - start;
                log.info("租户数据库 {} 克隆就绪，耗时: {} ms", dbName, duration);
            }
        } catch (Exception e) {
            log.error("租户物理库 {} 开辟失败: {}", dbName, e.getMessage(), e);
            throw new McoreSystemException(ErrorCode.SYSTEM_DATABASE_PROVISION_FAILED, e);
        }
    }

    /**
     * 强行下线并销毁租户数据库
     */
    public void dropTenantDatabase(String tenantId) {
        if (tenantId == null || !SAFE_TENANT_ID_PATTERN.matcher(tenantId).matches()) {
            throw new McoreBusinessException(ErrorCode.CLIENT_PARAM_ERROR.getCode(), "非法租户ID标识: " + tenantId);
        }

        String cleanId = tenantId.replace("-", "_").toLowerCase();
        String dbName = "mcore_u_" + cleanId;

        try (Connection conn = systemDataSource.getConnection()) {
            conn.setAutoCommit(true);
            try (Statement stmt = conn.createStatement()) {
                // 1. 驱逐该库所有活跃连接
                String killSql = String.format(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity " +
                    "WHERE datname = '%s' AND pid <> pg_backend_pid()", dbName
                );
                stmt.execute(killSql);

                // 2. 物理 DROP
                stmt.execute("DROP DATABASE IF EXISTS " + dbName);
                log.info("租户物理库 {} 及其连接已安全销毁", dbName);
            }
        } catch (Exception e) {
            log.error("销毁租户物理库 {} 失败: {}", dbName, e.getMessage(), e);
            throw new McoreSystemException(ErrorCode.SYSTEM_ERROR, e);
        }
    }
}
