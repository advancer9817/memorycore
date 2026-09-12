package org.mcore.storage.util;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.postgresql.util.PGobject;

import java.util.*;

/**
 * JSONB 列规范化工具。
 *
 * 问题背景：通过 JdbcClient 的 listOfRows() 读取 jsonb 列时，PostgreSQL 驱动返回的是
 * {@link PGobject} 实例，直接交给 Spring 序列化会输出驱动的内部结构：
 *   {"type":"jsonb","value":"{\"error\": ...}"}
 * 前端拿到的是包裹了一层的字符串，无法直接解析。
 *
 * 本工具把 PGobject 解包为真正的 JSON 结构（Map/List/标量），其余类型原样透传。
 */
public final class JsonbRows {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private JsonbRows() {
    }

    /** 就地规范化单行内的所有 jsonb 值 */
    public static Map<String, Object> row(Map<String, Object> raw) {
        if (raw == null) {
            return null;
        }
        Map<String, Object> out = new LinkedHashMap<>();
        for (Map.Entry<String, Object> e : raw.entrySet()) {
            out.put(e.getKey(), value(e.getValue()));
        }
        return out;
    }

    public static List<Map<String, Object>> rows(List<Map<String, Object>> raw) {
        if (raw == null) {
            return List.of();
        }
        List<Map<String, Object>> out = new ArrayList<>(raw.size());
        for (Map<String, Object> r : raw) {
            out.add(row(r));
        }
        return out;
    }

    /** 解包单个值：PGobject(json/jsonb) → 结构化对象 */
    public static Object value(Object v) {
        if (v instanceof PGobject pg) {
            String type = pg.getType();
            if (type != null && type.toLowerCase().contains("json")) {
                String raw = pg.getValue();
                if (raw == null || raw.isBlank()) {
                    return null;
                }
                try {
                    return MAPPER.readValue(raw, Object.class);
                } catch (Exception e) {
                    return raw; // 解析失败则退化为原始字符串，不丢数据
                }
            }
            return pg.getValue();
        }
        // 数组列（如 tags / related_ids 为 text[]）经驱动返回 java.sql.Array，
        // 若原样透传，Jackson 会 introspect 出驱动内部结构
        // （resultSet → statement → connection → parameterStatuses …），
        // 既泄漏连接信息，也会产出非法 JSON 使整个响应无法解析。
        if (v instanceof java.sql.Array arr) {
            try {
                Object a = arr.getArray();
                if (a instanceof Object[] objs) {
                    List<Object> list = new ArrayList<>(objs.length);
                    for (Object o : objs) {
                        list.add(o);
                    }
                    return list;
                }
                return a == null ? null : String.valueOf(a);
            } catch (Exception e) {
                return null;
            }
        }
        // 兜底：任何驱动自有类型都不许被 introspect，转为字符串
        if (v != null && v.getClass().getName().startsWith("org.postgresql.")) {
            return String.valueOf(v);
        }
        return v;
    }
}
