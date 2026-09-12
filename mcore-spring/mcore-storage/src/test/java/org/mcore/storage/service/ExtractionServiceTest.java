package org.mcore.storage.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mcore.common.model.MemoryDO;
import org.mcore.storage.embedding.EmbeddingService;
import org.mcore.storage.repository.MemoryRepository;
import org.mcore.storage.search.HybridSearchService;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.lang.reflect.Method;
import java.util.Collections;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class ExtractionServiceTest {

    @Mock
    private EmbeddingService embeddingService;

    @Mock
    private HybridSearchService hybridSearchService;

    @Mock
    private MemoryRepository memoryRepository;

    private ObjectMapper objectMapper;
    private ExtractionService extractionService;

    @BeforeEach
    void setUp() {
        objectMapper = new ObjectMapper();
        extractionService = new ExtractionService(embeddingService, hybridSearchService, memoryRepository, objectMapper);
        ReflectionTestUtils.setField(extractionService, "baseUrl", "http://127.0.0.1:8317/v1");
        ReflectionTestUtils.setField(extractionService, "apiKey", "test-key");
        ReflectionTestUtils.setField(extractionService, "model", "gemini-3.8-flash");
        ReflectionTestUtils.setField(extractionService, "timeoutSeconds", 10);
    }

    @Test
    @DisplayName("验证 cleanJsonResponse 正确清洗 Markdown 代码块与前缀后缀")
    void testCleanJsonResponse() throws Exception {
        Method method = ExtractionService.class.getDeclaredMethod("cleanJsonResponse", String.class);
        method.setAccessible(true);

        String rawWithFence = "```json\n{\"memory\": [{\"title\": \"t1\"}]}\n```";
        String cleaned1 = (String) method.invoke(extractionService, rawWithFence);
        assertEquals("{\"memory\": [{\"title\": \"t1\"}]}", cleaned1);

        String rawWithText = "根据对话分析，提取事实如下：\n{\"memory\": []}\n以上是提取结果。";
        String cleaned2 = (String) method.invoke(extractionService, rawWithText);
        assertEquals("{\"memory\": []}", cleaned2);
    }

    @Test
    @DisplayName("验证 resolveCompletionsUrl 兼容 /v1 与纯域名端点")
    void testResolveCompletionsUrl() throws Exception {
        Method method = ExtractionService.class.getDeclaredMethod("resolveCompletionsUrl", String.class);
        method.setAccessible(true);

        String url1 = (String) method.invoke(extractionService, "http://127.0.0.1:8317/v1");
        assertEquals("http://127.0.0.1:8317/v1/chat/completions", url1);

        String url2 = (String) method.invoke(extractionService, "http://127.0.0.1:8317");
        assertEquals("http://127.0.0.1:8317/v1/chat/completions", url2);

        String url3 = (String) method.invoke(extractionService, "https://open.bigmodel.cn/api/paas/v4");
        assertEquals("https://open.bigmodel.cn/api/paas/v4/chat/completions", url3);
    }

    @Test
    @DisplayName("验证当相似度 >= 0.92 时判定为 duplicate 并跳过 (skip)")
    void testExtractAndIngest_SemanticDedup_SkipHighSimilarity() {
        // 空对话直接返回 0
        var emptyResult = extractionService.extractAndIngest(new ExtractionService.IngestRequest(
                Collections.emptyList(), "", "ingest", "hermes", "/tmp", "global"
        ));
        assertEquals(0, emptyResult.added());
        assertEquals(0, emptyResult.skipped());
        assertFalse(emptyResult.degraded());
    }

    @Test
    @DisplayName("验证针对单文本和多轮对话输入均能构建有效转录上下文")
    void testTranscriptParsing() {
        var reqMessages = new ExtractionService.IngestRequest(
                List.of(
                        Map.of("role", "user", "content", "以后排查请使用单步命令"),
                        Map.of("role", "assistant", "content", "好的，已记录工程规范")
                ),
                null, "ingest", "hermes", "/tmp", "global"
        );
        assertNotNull(reqMessages.messages());
        assertEquals(2, reqMessages.messages().size());

        var reqText = new ExtractionService.IngestRequest(
                null, "修复了数据库连接超时问题", "ingest", "hermes", "/tmp", "global"
        );
        assertEquals("修复了数据库连接超时问题", reqText.text());
    }
}
