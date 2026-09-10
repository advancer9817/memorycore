package org.mcore.server.controller;

import jakarta.servlet.http.HttpServletRequest;
import org.mcore.mcp.protocol.JsonRpcRequest;
import org.mcore.mcp.protocol.JsonRpcResponse;
import org.mcore.mcp.service.McpProtocolService;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;
import java.util.UUID;

@RestController
@RequestMapping("/mcp")
public class McpController {

    private final McpProtocolService mcpProtocolService;

    public McpController(McpProtocolService mcpProtocolService) {
        this.mcpProtocolService = mcpProtocolService;
    }

    @PostMapping(consumes = MediaType.APPLICATION_JSON_VALUE, produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<JsonRpcResponse> handleJsonRpc(@RequestBody JsonRpcRequest request, HttpServletRequest httpRequest) {
        String callerAgent = (String) httpRequest.getAttribute("caller_agent");
        String sessionId = httpRequest.getHeader("Mcp-Session-Id");
        if (sessionId == null || sessionId.isBlank()) {
            sessionId = UUID.randomUUID().toString();
        }
        JsonRpcResponse resp = mcpProtocolService.handleRequest(request, callerAgent);
        return ResponseEntity.ok()
                .header("Mcp-Session-Id", sessionId)
                .body(resp);
    }

    @GetMapping(produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> getServerInfo() {
        return Map.of(
                "name", "mcore",
                "version", "0.26.0",
                "protocolVersion", "2024-11-05",
                "status", "online"
        );
    }
}
