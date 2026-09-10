package org.mcore.server.controller;

import org.mcore.common.result.Result;
import org.mcore.storage.service.StatsService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/api/v1")
public class StatsController {

    private final StatsService statsService;

    public StatsController(StatsService statsService) {
        this.statsService = statsService;
    }

    @GetMapping("/stats")
    public Map<String, Object> stats() {
        return statsService.getMemoryStats();
    }

    @GetMapping("/health-score")
    public Map<String, Object> healthScore() {
        return statsService.getHealthScorePayload();
    }

    @GetMapping("/dashboard")
    public Result<Map<String, Object>> dashboard() {
        return Result.success(statsService.getHealthScorePayload());
    }
}
