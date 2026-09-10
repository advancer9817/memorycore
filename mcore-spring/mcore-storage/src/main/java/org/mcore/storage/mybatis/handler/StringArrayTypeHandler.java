package org.mcore.storage.mybatis.handler;

import org.apache.ibatis.type.BaseTypeHandler;
import org.apache.ibatis.type.JdbcType;

import java.sql.Array;
import java.sql.CallableStatement;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * MyBatis PostgreSQL 原生 TEXT[] 数组列与 Java List&lt;String&gt; 双向映射处理器
 * 适用列：memories.tags、memories.related_ids
 */
public class StringArrayTypeHandler extends BaseTypeHandler<List<String>> {

    @Override
    public void setNonNullParameter(PreparedStatement ps, int i, List<String> parameter, JdbcType jdbcType)
            throws SQLException {
        Array array = ps.getConnection().createArrayOf("text", parameter.toArray(new String[0]));
        ps.setArray(i, array);
    }

    @Override
    public List<String> getNullableResult(ResultSet rs, String columnName) throws SQLException {
        return toList(rs.getArray(columnName));
    }

    @Override
    public List<String> getNullableResult(ResultSet rs, int columnIndex) throws SQLException {
        return toList(rs.getArray(columnIndex));
    }

    @Override
    public List<String> getNullableResult(CallableStatement cs, int columnIndex) throws SQLException {
        return toList(cs.getArray(columnIndex));
    }

    private List<String> toList(Array array) throws SQLException {
        if (array == null) {
            return new ArrayList<>();
        }
        try {
            Object raw = array.getArray();
            if (raw instanceof Object[] objects) {
                List<String> out = new ArrayList<>(objects.length);
                for (Object obj : objects) {
                    if (obj != null) {
                        out.add(String.valueOf(obj));
                    }
                }
                return out;
            }
            return new ArrayList<>();
        } catch (SQLException e) {
            return Collections.emptyList();
        } finally {
            try {
                array.free();
            } catch (SQLException ignored) {
                // 释放失败不影响业务
            }
        }
    }
}
