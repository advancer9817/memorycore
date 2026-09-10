package org.mcore.storage.mybatis.handler;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.ibatis.type.BaseTypeHandler;
import org.apache.ibatis.type.JdbcType;

import java.sql.CallableStatement;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.HashMap;
import java.util.Map;

/**
 * MyBatis PostgreSQL 原生 JSONB 列与 Java Map 双向映射处理器
 * 适用列：memories.metadata
 */
public class JsonMapTypeHandler extends BaseTypeHandler<Map<String, Object>> {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Override
    public void setNonNullParameter(PreparedStatement ps, int i, Map<String, Object> parameter, JdbcType jdbcType)
            throws SQLException {
        try {
            ps.setObject(i, MAPPER.writeValueAsString(parameter), java.sql.Types.OTHER);
        } catch (Exception e) {
            throw new SQLException("序列化 JSONB 参数失败: " + e.getMessage(), e);
        }
    }

    @Override
    public Map<String, Object> getNullableResult(ResultSet rs, String columnName) throws SQLException {
        return parse(rs.getString(columnName));
    }

    @Override
    public Map<String, Object> getNullableResult(ResultSet rs, int columnIndex) throws SQLException {
        return parse(rs.getString(columnIndex));
    }

    @Override
    public Map<String, Object> getNullableResult(CallableStatement cs, int columnIndex) throws SQLException {
        return parse(cs.getString(columnIndex));
    }

    private Map<String, Object> parse(String raw) {
        if (raw == null || raw.isBlank()) {
            return new HashMap<>();
        }
        try {
            return MAPPER.readValue(raw, new TypeReference<Map<String, Object>>() {});
        } catch (Exception e) {
            return new HashMap<>();
        }
    }
}
