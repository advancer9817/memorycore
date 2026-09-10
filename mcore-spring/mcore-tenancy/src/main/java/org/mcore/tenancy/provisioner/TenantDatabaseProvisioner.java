package org.mcore.tenancy.provisioner;

import org.mcore.common.exception.McoreBusinessException;
import org.mcore.common.exception.McoreSystemException;
import org.mcore.common.result.ErrorCode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.Statement;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * 租户物理数据库生命周期开辟与销毁引擎
 * <p>
 * 职责双写闭环：
 * ① 数据面 —— 基于 template_mcore 模板库毫秒级物理写时复制（COW）开辟 / 销毁独立数据库；
 * ② 控制面 —— 同步维护 mcore_system.sys_tenant_databases 注册表与 sys_tenant_quotas 配额记录。
 */
@Component
public class TenantDatabaseProvisioner {
    private static final Logger log = LoggerFactory.getLogger(TenantDatabaseProvisioner.class);
    private static final Pattern SAFE_TENANT_ID_PATTERN = Pattern.compile("^[a-zA-Z0-9_-]{1,32}$");

    private static final int DEFAULT_MAX_MEMORIES = 10000;
    private static final int DEFAULT_MAX_STORAGE_MB = 512;

    private final DataSource defaultDataSource;
    private final JdbcClient systemJdbcClient;

    public TenantDatabaseProvisioner(@Qualifier("defaultDataSource") DataSource defaultDataSource,
                                     @Qualifier("systemJdbcClient") JdbcClient systemJdbcClient) {
        this.defaultDataSource = defaultDataSource;
        this.systemJdbcClient = systemJdbcClient;
    }

    /**
     * 基于 template_mcore 毫秒级物理写时复制（COW）开辟新租户数据库，并同步登记控制面注册表
     */
    public void provisionTenantDatabase(String tenantId, String dbUser) {
        validateTenantId(tenantId);
        String dbName = toDbName(tenantId);

        boolean created = createDatabaseIfAbsent(dbName, dbUser);
        registerTenant(tenantId, dbName, dbUser, created ? "ready" : "ready");
    }

    /**
     * 强行下线并销毁租户数据库，并同步清理控制面注册表
     */
    public void dropTenantDatabase(String tenantId) {
        validateTenantId(tenantId);
        String dbName = toDbName(tenantId);

        try (Connection conn = defaultDataSource.getConnection()) {
            conn.setAutoCommit(true);
            try (Statement stmt = conn.createStatement()) {
                // 1. 驱逐该库所有活跃连接
                stmt.execute(String.format(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity " +
                        "WHERE datname = '%s' AND pid <> pg_backend_pid()", dbName));

                // 2. 物理 DROP
                stmt.execute("DROP DATABASE IF EXISTS " + dbName);
                log.info("租户物理库 {} 及其连接已安全销毁", dbName);
            }
        } catch (Exception e) {
            log.error("销毁租户物理库 {} 失败: {}", dbName, e.getMessage(), e);
            throw new McoreSystemException(ErrorCode.SYSTEM_ERROR, e);
        }

        // 3. 控制面注册表清理
        try {
            systemJdbcClient.sql("DELETE FROM sys_tenant_api_keys WHERE tenant_id = ?").param(tenantId).update();
            systemJdbcClient.sql("DELETE FROM sys_tenant_quotas WHERE tenant_id = ?").param(tenantId).update();
            systemJdbcClient.sql("DELETE FROM sys_tenant_databases WHERE tenant_id = ?").param(tenantId).update();
            log.info("控制面注册表已清理租户 {}", tenantId);
        } catch (Exception e) {
            log.warn("控制面注册表清理租户 {} 失败（物理库已销毁）: {}", tenantId, e.getMessage());
        }
    }

    /**
     * 查询控制面全部已登记租户
     */
    public List<Map<String, Object>> listTenants() {
        return systemJdbcClient.sql("""
                SELECT tenant_id, db_name, db_user, db_host, db_port,
                       schema_version, status, created_at
                FROM sys_tenant_databases
                ORDER BY created_at DESC
                """).query((rs, rowNum) -> {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("tenant_id", rs.getString("tenant_id"));
            row.put("db_name", rs.getString("db_name"));
            row.put("db_user", rs.getString("db_user"));
            row.put("db_host", rs.getString("db_host"));
            row.put("db_port", rs.getInt("db_port"));
            row.put("schema_version", rs.getInt("schema_version"));
            row.put("status", rs.getString("status"));
            row.put("created_at", rs.getString("created_at"));
            return row;
        }).list();
    }

    // ------------------------------------------------------------------
    // 内部实现
    // ------------------------------------------------------------------

    /**
     * @return true 表示本次新建了物理库，false 表示已存在
     */
    private boolean createDatabaseIfAbsent(String dbName, String dbUser) {
        try (Connection conn = defaultDataSource.getConnection()) {
            conn.setAutoCommit(true);
            try (Statement stmt = conn.createStatement()) {
                var rs = stmt.executeQuery(
                        "SELECT 1 FROM pg_database WHERE datname = '" + dbName + "'");
                if (rs.next()) {
                    log.info("租户物理库 {} 已存在，跳过克隆，仅刷新控制面注册表", dbName);
                    return false;
                }
            }

            try (Statement stmt = conn.createStatement()) {
                long start = System.currentTimeMillis();
                stmt.execute(String.format(
                        "CREATE DATABASE %s WITH TEMPLATE template_mcore OWNER %s", dbName, dbUser));
                log.info("租户物理库 {} 克隆就绪，耗时: {} ms", dbName, System.currentTimeMillis() - start);
            }
            return true;
        } catch (Exception e) {
            log.error("租户物理库 {} 开辟失败: {}", dbName, e.getMessage(), e);
            throw new McoreSystemException(ErrorCode.SYSTEM_DATABASE_PROVISION_FAILED, e);
        }
    }

    /**
     * 向控制面注册表 UPSERT 租户记录，并确保用户行与配额行存在
     */
    private void registerTenant(String tenantId, String dbName, String dbUser, String status) {
        try {
            // 0. 确保 sys_users 用户行存在（外键依赖），锁定态 '!' 表示尚未设置密码，不可密码登录
            systemJdbcClient.sql("""
                    INSERT INTO sys_users (id, username, password_hash, display_name, status)
                    VALUES (?, ?, '!', ?, 'active')
                    ON CONFLICT (id) DO NOTHING
                    """)
                    .param(tenantId).param(tenantId).param(tenantId)
                    .update();

            systemJdbcClient.sql("""
                    INSERT INTO sys_tenant_databases
                        (tenant_id, db_name, db_user, db_host, db_port, schema_version, status)
                    VALUES (?, ?, ?, '127.0.0.1', 5432, 1, ?)
                    ON CONFLICT (tenant_id) DO UPDATE
                        SET db_name = EXCLUDED.db_name,
                            db_user = EXCLUDED.db_user,
                            status = EXCLUDED.status
                    """)
                    .param(tenantId).param(dbName).param(dbUser).param(status)
                    .update();

            systemJdbcClient.sql("""
                    INSERT INTO sys_tenant_quotas (tenant_id, max_memories, max_storage_mb)
                    VALUES (?, ?, ?)
                    ON CONFLICT (tenant_id) DO NOTHING
                    """)
                    .param(tenantId).param(DEFAULT_MAX_MEMORIES).param(DEFAULT_MAX_STORAGE_MB)
                    .update();

            log.info("控制面注册表已登记租户 {} -> {}", tenantId, dbName);
        } catch (Exception e) {
            log.error("控制面注册租户 {} 失败（物理库已创建）: {}", tenantId, e.getMessage(), e);
            throw new McoreSystemException(ErrorCode.SYSTEM_ERROR, e);
        }
    }

    private void validateTenantId(String tenantId) {
        if (tenantId == null || !SAFE_TENANT_ID_PATTERN.matcher(tenantId).matches()) {
            throw new McoreBusinessException(ErrorCode.CLIENT_PARAM_ERROR.getCode(), "非法租户ID标识: " + tenantId);
        }
    }

    private String toDbName(String tenantId) {
        return "mcore_u_" + tenantId.replace("-", "_").toLowerCase();
    }
}
