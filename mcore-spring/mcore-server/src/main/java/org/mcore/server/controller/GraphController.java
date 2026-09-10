package org.mcore.server.controller;

import org.mcore.storage.service.GraphService;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api/v1")
public class GraphController {

    private final GraphService graphService;

    public GraphController(GraphService graphService) {
        this.graphService = graphService;
    }

    @GetMapping("/graph")
    public Map<String, Object> getGraph(@RequestParam(value = "limit", defaultValue = "150") int limit) {
        return graphService.getGraphData(limit);
    }
}
