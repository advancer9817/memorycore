package org.mcore.storage.service;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.util.*;

@Service
public class GraphService {

    private final JdbcClient jdbcClient;

    public GraphService(JdbcClient jdbcClient) {
        this.jdbcClient = jdbcClient;
    }

    public Map<String, Object> getGraphData(int limit) {
        if (limit <= 0) limit = 150;

        // 1. 获取活跃节点
        String nodeSql = """
            SELECT id, title, type, status, importance, scope, source_agent
            FROM memories
            WHERE status = 'active'
            ORDER BY importance DESC, updated_at DESC
            LIMIT :limit
        """;
        List<Map<String, Object>> nodeRows = jdbcClient.sql(nodeSql).param("limit", limit).query().listOfRows();
        Set<String> nodeIds = new HashSet<>();
        List<Map<String, Object>> nodes = new ArrayList<>();

        for (Map<String, Object> r : nodeRows) {
            String id = String.valueOf(r.get("id"));
            nodeIds.add(id);
            Map<String, Object> node = new LinkedHashMap<>();
            node.put("id", id);
            node.put("name", r.get("title") != null && !String.valueOf(r.get("title")).isBlank() ? r.get("title") : id);
            node.put("label", node.get("name"));
            node.put("type", r.get("type"));
            node.put("status", r.get("status"));
            node.put("importance", r.get("importance"));
            node.put("source_agent", r.get("source_agent"));
            nodes.add(node);
        }

        // 2. 获取节点间的关联边
        List<Map<String, Object>> links = new ArrayList<>();
        if (!nodeIds.isEmpty()) {
            String linkSql = """
                SELECT id, source_id, target_id, relation_type, weight
                FROM memory_links
                WHERE source_id IN (:nids) AND target_id IN (:nids)
            """;
            List<Map<String, Object>> linkRows = jdbcClient.sql(linkSql).param("nids", nodeIds).query().listOfRows();
            for (Map<String, Object> r : linkRows) {
                Map<String, Object> link = new LinkedHashMap<>();
                link.put("id", r.get("id"));
                link.put("source", r.get("source_id"));
                link.put("target", r.get("target_id"));
                link.put("relation", r.get("relation_type"));
                link.put("weight", r.get("weight"));
                links.add(link);
            }
        }

        Map<String, Object> res = new LinkedHashMap<>();
        res.put("nodes", nodes);
        res.put("links", links);
        res.put("total_nodes", nodes.size());
        res.put("total_links", links.size());
        return res;
    }
}
