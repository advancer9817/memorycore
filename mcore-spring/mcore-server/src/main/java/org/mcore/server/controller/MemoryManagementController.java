package org.mcore.server.controller;

import org.mcore.storage.service.MemoryQueryService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.time.Instant;
import java.util.*;

@RestController
public class MemoryManagementController {

    private final MemoryQueryService memoryQueryService;

    public MemoryManagementController(MemoryQueryService memoryQueryService) {
        this.memoryQueryService = memoryQueryService;
    }

    @PostMapping({"/api/v1/memories/filter", "/api/v1/memories/filter/"})
    public Map<String, Object> filterMemoriesPost(@RequestBody(required = false) Map<String, Object> body) {
        return memoryQueryService.filterMemories(body != null ? body : Map.of());
    }

    @GetMapping({"/api/v1/memories/filter", "/api/v1/memories/filter/"})
    public Map<String, Object> filterMemoriesGet(@RequestParam Map<String, Object> params) {
        return memoryQueryService.filterMemories(params);
    }

    @GetMapping({"/api/v1/memories", "/api/v1/memories/"})
    public Map<String, Object> listMemories(@RequestParam Map<String, Object> params) {
        return memoryQueryService.filterMemories(params);
    }

    @PostMapping({"/api/v1/memories", "/api/v1/memories/"})
    public Map<String, Object> createMemory(@RequestBody Map<String, Object> body) {
        return memoryQueryService.createMemory(body != null ? body : Map.of());
    }

    @SuppressWarnings("unchecked")
    @DeleteMapping({"/api/v1/memories", "/api/v1/memories/"})
    public Map<String, Object> deleteMemoriesBatch(@RequestBody(required = false) Map<String, Object> body) {
        List<String> ids = body != null && body.get("memory_ids") != null ? (List<String>) body.get("memory_ids") : Collections.emptyList();
        boolean ok = memoryQueryService.batchUpdateStatus(ids, "archived");
        return Map.of("success", ok, "archived", ids, "count", ids.size());
    }

    @GetMapping({"/api/v1/memories/categories", "/api/v1/memories/categories/", "/api/v1/categories", "/api/v1/categories/"})
    public Map<String, Object> getCategories() {
        List<Map<String, Object>> raw = memoryQueryService.getCategories();
        List<Map<String, Object>> categories = new ArrayList<>();
        for (Map<String, Object> c : raw) {
            Map<String, Object> m = new LinkedHashMap<>(c);
            String name = String.valueOf(c.getOrDefault("name", c.get("category_id")));
            m.putIfAbsent("id", name);
            m.putIfAbsent("name", name);
            m.putIfAbsent("description", name);
            m.putIfAbsent("created_at", Instant.now().toString());
            m.putIfAbsent("updated_at", Instant.now().toString());
            categories.add(m);
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("categories", categories);
        res.put("total", categories.size());
        return res;
    }

    @GetMapping({"/api/v1/tags", "/api/v1/tags/"})
    public Map<String, Object> getTags() {
        List<Map<String, Object>> raw = memoryQueryService.getCategories();
        List<String> tags = raw.stream()
                .map(c -> String.valueOf(c.getOrDefault("name", c.get("category_id"))))
                .filter(s -> s != null && !s.isBlank())
                .toList();
        return Map.of("tags", tags, "total", tags.size());
    }

    @GetMapping({"/api/v1/memories/{id}", "/api/v1/memories/{id}/"})
    public ResponseEntity<Map<String, Object>> getMemory(@PathVariable("id") String id) {
        Map<String, Object> detail = memoryQueryService.getMemoryDetail(id);
        if (detail == null) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok(detail);
    }

    @PutMapping({"/api/v1/memories/{id}", "/api/v1/memories/{id}/"})
    public ResponseEntity<Map<String, Object>> updateMemory(
            @PathVariable("id") String id,
            @RequestBody Map<String, Object> body) {
        String title = (String) body.get("title");
        String content = body.get("content") != null ? (String) body.get("content") : (String) body.get("text");
        Double importance = body.get("importance") != null ? ((Number) body.get("importance")).doubleValue() : null;
        String status = (String) body.get("status");

        boolean ok = memoryQueryService.updateMemory(id, title, content, importance, status);
        if (!ok) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok(Map.of("success", true, "id", id));
    }

    @DeleteMapping({"/api/v1/memories/{id}", "/api/v1/memories/{id}/"})
    public ResponseEntity<Map<String, Object>> deleteMemory(@PathVariable("id") String id) {
        boolean ok = memoryQueryService.updateMemory(id, null, null, null, "archived");
        return ResponseEntity.ok(Map.of("success", ok, "id", id, "status", "archived"));
    }

    @SuppressWarnings("unchecked")
    @PostMapping({"/api/v1/memories/actions/pause", "/api/v1/memories/actions/pause/"})
    public Map<String, Object> batchPauseOrActivate(@RequestBody Map<String, Object> body) {
        String state = String.valueOf(body.getOrDefault("state", "archived"));
        String targetStatus = "active".equalsIgnoreCase(state) ? "active" : "archived";
        List<String> ids = (List<String>) body.get("memory_ids");
        if (ids == null) ids = Collections.emptyList();

        memoryQueryService.batchUpdateStatus(ids, targetStatus);
        return Map.of("updated", ids, "state", state);
    }

    @GetMapping({"/api/v1/memories/{id}/access-log", "/api/v1/memories/{id}/access-log/"})
    public Map<String, Object> getAccessLog(@PathVariable("id") String id,
                                            @RequestParam(value = "page", defaultValue = "1") int page,
                                            @RequestParam(value = "page_size", defaultValue = "10") int pageSize) {
        return memoryQueryService.getAccessLogs(id, page, pageSize);
    }

    @GetMapping({"/api/v1/memories/{id}/related", "/api/v1/memories/{id}/related/"})
    public Map<String, Object> getRelatedMemories(@PathVariable("id") String id) {
        return memoryQueryService.getRelatedMemories(id);
    }

    @GetMapping({"/api/lineage/{id}", "/api/lineage/{id}/", "/api/v1/lineage/{id}"})
    public Map<String, Object> getLineage(@PathVariable("id") String id) {
        return memoryQueryService.getLineage(id);
    }
}
