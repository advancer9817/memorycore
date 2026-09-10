package org.mcore.server.config;

import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import org.mcore.tenancy.pool.DynamicTenantRoutingDataSource;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import org.springframework.jdbc.core.simple.JdbcClient;

import javax.sql.DataSource;

@Configuration
public class DataSourceConfig {

    @Value("${spring.datasource.host:127.0.0.1}")
    private String host;

    @Value("${spring.datasource.port:5432}")
    private int port;

    @Value("${spring.datasource.username:mcore_user}")
    private String username;

    @Value("${spring.datasource.password:mcore_secure_password_2026}")
    private String password;

    @Value("${spring.datasource.default-db:mcore}")
    private String defaultDb;

    @Value("${spring.datasource.system-db:mcore_system}")
    private String systemDb;

    @Bean
    public DataSource defaultDataSource() {
        HikariConfig config = new HikariConfig();
        config.setJdbcUrl(String.format("jdbc:postgresql://%s:%d/%s?sslmode=prefer&ApplicationName=mcore_default", host, port, defaultDb));
        config.setUsername(username);
        config.setPassword(password);
        config.setPoolName("Hikari-Default-Pool");
        config.setMinimumIdle(2);
        config.setMaximumPoolSize(5);
        config.setIdleTimeout(300000);
        return new HikariDataSource(config);
    }

    /**
     * 控制面系统库（租户注册表 / 用户 / 配额 / 密钥）专用数据源
     */
    @Bean
    public DataSource systemDataSource() {
        HikariConfig config = new HikariConfig();
        config.setJdbcUrl(String.format("jdbc:postgresql://%s:%d/%s?sslmode=prefer&ApplicationName=mcore_system", host, port, systemDb));
        config.setUsername(username);
        config.setPassword(password);
        config.setPoolName("Hikari-System-Pool");
        config.setMinimumIdle(1);
        config.setMaximumPoolSize(3);
        config.setIdleTimeout(300000);
        return new HikariDataSource(config);
    }

    @Bean
    public JdbcClient systemJdbcClient(@Qualifier("systemDataSource") DataSource systemDataSource) {
        return JdbcClient.create(systemDataSource);
    }

    @Bean
    @Primary
    public DataSource dynamicDataSource(@Qualifier("defaultDataSource") DataSource defaultDataSource) {
        return new DynamicTenantRoutingDataSource(host, port, username, password, defaultDataSource);
    }

    @Bean
    public JdbcClient jdbcClient(DataSource dynamicDataSource) {
        return JdbcClient.create(dynamicDataSource);
    }
}
