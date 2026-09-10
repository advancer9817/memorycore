package org.mcore.storage.repository;

import org.mcore.common.model.MemoryLinkDO;
import org.mcore.storage.mapper.LinkMapper;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

import java.util.*;

@Repository
public class LinkRepository {

    private final LinkMapper linkMapper;
    private final JdbcClient jdbcClient;

    public LinkRepository(LinkMapper linkMapper, JdbcClient jdbcClient) {
        this.linkMapper = linkMapper;
        this.jdbcClient = jdbcClient;
    }

    public long count() {
        return jdbcClient.sql("SELECT count(*) FROM memory_links").query(Long.class).single();
    }

    public MemoryLinkDO addLink(String sourceId, String targetId, String relationType, Double weight, String note, String agent) {
        String linkId = "lnk_" + UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        String rel = (relationType != null && !relationType.isBlank()) ? relationType : "related_to";
        double w = weight != null ? Math.max(0.0, Math.min(1.0, weight)) : 1.0;
        String n = note != null ? note : "";
        String ag = agent != null ? agent : "agent";

        MemoryLinkDO link = new MemoryLinkDO();
        link.setId(linkId);
        link.setSourceId(sourceId);
        link.setTargetId(targetId);
        link.setRelationType(rel);
        link.setWeight(w);
        link.setNote(n);
        link.setSourceAgent(ag);

        linkMapper.insert(link);
        return link;
    }

    public Map<String, Object> queryLinks(String memoryId, String direction, String relationType, int limit) {
        List<Map<String, Object>> links = linkMapper.selectLineageLinks(memoryId);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("memory_id", memoryId);
        result.put("links", links);
        result.put("total", links.size());
        return result;
    }

    public Map<String, Object> getGraphData(int limit) {
        int cap = limit > 0 ? Math.min(limit, 300) : 100;
        List<Map<String, Object>> nodes = linkMapper.selectGraphNodes(cap);
        List<Map<String, Object>> rawLinks = linkMapper.selectGraphEdges(cap);

        Set<String> validNodeIds = new HashSet<>();
        List<Map<String, Object>> formattedNodes = new ArrayList<>();
        for (var n : nodes) {
            String id = String.valueOf(n.get("id"));
            validNodeIds.add(id);
            Map<String, Object> node = new LinkedHashMap<>();
            node.put("id", id);
            String title = (String) n.get("title");
            node.put("name", (title != null && !title.isBlank()) ? title : id.substring(0, Math.min(8, id.length())));
            node.put("category", n.get("type"));
            node.put("value", n.get("importance"));
            formattedNodes.add(node);
        }

        List<Map<String, Object>> validLinks = new ArrayList<>();
        for (var l : rawLinks) {
            String s = String.valueOf(l.get("source_id"));
            String t = String.valueOf(l.get("target_id"));
            if (validNodeIds.contains(s) && validNodeIds.contains(t)) {
                Map<String, Object> edge = new LinkedHashMap<>();
                edge.put("source", s);
                edge.put("target", t);
                edge.put("relation", l.get("relation_type"));
                edge.put("weight", l.get("weight"));
                validLinks.add(edge);
            }
        }

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("nodes", formattedNodes);
        data.put("links", validLinks);
        data.put("total_nodes", formattedNodes.size());
        data.put("total_links", validLinks.size());
        return data;
    }
}
