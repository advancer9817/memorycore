package org.mcore.mcp.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mcore.mcp.protocol.JsonRpcRequest;
import org.mcore.mcp.protocol.JsonRpcResponse;
import org.mcore.storage.pack.ContextPackBuilder;
import org.mcore.storage.repository.EntityRepository;
import org.mcore.storage.repository.FeedbackRepository;
import org.mcore.storage.repository.LinkRepository;
import org.mcore.storage.repository.MemoryRepository;
import org.mcore.storage.search.HybridSearchService;
import org.mcore.storage.service.ExtractionService;
import org.mcore.storage.transfer.TransferService;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class McpProtocolServiceTest {

    @Mock
    private HybridSearchService hybridSearchService;

    @Mock
    private ContextPackBuilder contextPackBuilder;

    @Mock
    private MemoryRepository memoryRepository;

    @Mock
    private LinkRepository linkRepository;

    @Mock
    private EntityRepository entityRepository;

    @Mock
    private FeedbackRepository feedbackRepository;

    @Mock
    private TransferService transferService;

    @Mock
    private ExtractionService extractionService;

    @Mock
    private org.mcore.storage.repository.QualityMetricsRepository qualityMetricsRepository;

    private ObjectMapper objectMapper;
    private McpProtocolService mcpProtocolService;

    @BeforeEach
    void setUp() {
        objectMapper = new ObjectMapper();
        mcpProtocolService = new McpProtocolService(
                hybridSearchService,
                contextPackBuilder,
                memoryRepository,
                linkRepository,
                entityRepository,
                feedbackRepository,
                transferService,
                extractionService,
                qualityMetricsRepository,
                objectMapper
        );
    }

    @Test
    @DisplayName("验证 tools/call memory_ingest 正确提取 messages 并调用 ExtractionService")
    void testMemoryIngestToolsCall() throws Exception {
        when(extractionService.extractAndIngest(any())).thenReturn(
                new ExtractionService.IngestResult(
                        1, 0, 0, 0,
                        List.of("新提取规范"),
                        List.of(),
                        List.of(),
                        1.2, 0.9, false, null
                )
        );

        String jsonReq = """
        {
            "jsonrpc": "2.0",
            "id": 101,
            "method": "tools/call",
            "params": {
                "name": "memory_ingest",
                "arguments": {
                    "messages": [
                        {"role": "user", "content": "以后排查命令单步给出"},
                        {"role": "assistant", "content": "好的，已确认"}
                    ],
                    "agent_id": "hermes",
                    "project_path": "/home/advancer/project/memorycore",
                    "scope": "project"
                }
            }
        }
        """;

        JsonNode reqNode = objectMapper.readTree(jsonReq);
        JsonRpcRequest request = new JsonRpcRequest();
        request.setId(101);
        request.setMethod("tools/call");
        request.setParams(reqNode.get("params"));

        JsonRpcResponse response = mcpProtocolService.handleRequest(request, "hermes");
        assertNotNull(response);
        assertNull(response.getError());

        @SuppressWarnings("unchecked")
        Map<String, Object> result = (Map<String, Object>) response.getResult();
        assertNotNull(result);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> contentList = (List<Map<String, Object>>) result.get("content");
        assertEquals(1, contentList.size());

        String textPayload = (String) contentList.get(0).get("text");
        JsonNode data = objectMapper.readTree(textPayload);
        assertEquals(1, data.get("added").asInt());
        assertEquals("新提取规范", data.get("added_titles").get(0).asText());

        ArgumentCaptor<ExtractionService.IngestRequest> captor = ArgumentCaptor.forClass(ExtractionService.IngestRequest.class);
        verify(extractionService, times(1)).extractAndIngest(captor.capture());
        var captured = captor.getValue();
        assertEquals(2, captured.messages().size());
        assertEquals("hermes", captured.agentId());
        assertEquals("/home/advancer/project/memorycore", captured.projectPath());
        assertEquals("project", captured.scope());
    }
}
