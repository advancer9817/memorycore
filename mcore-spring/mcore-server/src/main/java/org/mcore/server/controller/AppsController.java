package org.mcore.server.controller;

import org.mcore.storage.service.MemoryQueryService;
import org.mcore.storage.service.StatsService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.*;

@RestController
public class AppsController {

    private final StatsService statsService;
    private final MemoryQueryService memoryQueryService;

    public AppsController(StatsService statsService, MemoryQueryService memoryQueryService) {
        this.statsService = statsService;
        this.memoryQueryService = memoryQueryService;
    }

    @GetMapping({"/apps", "/apps/", "/api/v1/apps", "/api/v1/apps/"})
    public Map<String, Object> listApps() {
        List<Map<String, Object>> apps = statsService.getAppsList();
        return Map.of("apps", apps, "total", apps.size());
    }

    @GetMapping({"/apps/{appId}", "/apps/{appId}/", "/api/v1/apps/{appId}", "/api/v1/apps/{appId}/"})
    public ResponseEntity<Map<String, Object>> getAppDetails(@PathVariable("appId") String appId) {
        List<Map<String, Object>> apps = statsService.getAppsList();
        for (Map<String, Object> app : apps) {
            if (appId.equalsIgnoreCase(String.valueOf(app.get("id")))) {
                return ResponseEntity.ok(app);
            }
        }
        // 修复：此前对不存在的 app 伪造 {status:"idle", total_memories_created:0}，
        // 前端无法区分"空 app"与"不存在"。现如实返回 404。
        Map<String, Object> err = new LinkedHashMap<>();
        err.put("error", "app_not_found");
        err.put("message", "应用不存在: " + appId);
        err.put("app_id", appId);
        return ResponseEntity.status(404).body(err);
    }

    @GetMapping({"/apps/{appId}/memories", "/apps/{appId}/memories/", "/api/v1/apps/{appId}/memories", "/api/v1/apps/{appId}/memories/"})
    public Map<String, Object> getAppMemories(@PathVariable("appId") String appId,
                                              @RequestParam(defaultValue = "1") int page,
                                              @RequestParam(defaultValue = "50") int page_size) {
        Map<String, Object> params = new HashMap<>();
        params.put("app_ids", List.of(appId));
        params.put("page", page);
        params.put("size", page_size);
        return memoryQueryService.filterMemories(params);
    }

    @GetMapping({"/apps/{appId}/accessed", "/apps/{appId}/accessed/", "/api/v1/apps/{appId}/accessed", "/api/v1/apps/{appId}/accessed/"})
    public Map<String, Object> getAppAccessed(@PathVariable("appId") String appId,
                                              @RequestParam(defaultValue = "1") int page,
                                              @RequestParam(defaultValue = "50") int page_size) {
        // 修复：此前复用 filterMemories 返回该 app 的全部记忆，与"访问过"语义无关；
        // 现按真实 last_accessed_at 排序并只返回被访问过的记录。
        return memoryQueryService.listAccessedMemories(List.of(appId), page, page_size);
    }
}
