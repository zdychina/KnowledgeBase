package com.coremasterkb.serving.integration;

import com.coremasterkb.serving.application.QueryUnderstandingEngine;
import com.coremasterkb.serving.domain.QueryUnderstanding;
import com.coremasterkb.serving.infrastructure.EmbeddingClient;
import com.coremasterkb.serving.infrastructure.LlmClient;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.*;
import org.springframework.web.client.RestTemplate;

import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * Latency breakdown diagnostic for query_understanding stage.
 *
 * <p>LLM侧单个问题查询约2秒，但Java侧整体约4秒。
 * 本测试逐层拆解，定位额外开销来自哪里。
 *
 * <p>Test levels (from lowest to highest):
 * <ol>
 *   <li>Raw HTTP call to /api/v1/execute (纯HTTP层)</li>
 *   <li>LlmClient.execute() (HTTP + payload构建 + response解析)</li>
 *   <li>QueryUnderstandingEngine.understand() (LlmClient + unwrapResponse + parseLlmOutput)</li>
 *   <li>Embedding + Understanding 并行执行 (模拟SearchService并行)</li>
 * </ol>
 *
 * <p>Requires llm_service running at http://localhost:8900.
 */
@Tag("pg-integration")
@DisplayName("Query Understanding Latency Breakdown")
class QueryUnderstandingLatencyTest {

    private static final String BASE_URL = "http://localhost:8900";
    private static final String TEST_QUERY = "SMF是什么网元";
    private static RestTemplate restTemplate;

    @BeforeAll
    static void setUp() {
        // Use Apache HttpClient 5 connection pool (same as production ServingBeans)
        org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManager connPool =
                new org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManager();
        connPool.setDefaultConnectionConfig(org.apache.hc.client5.http.config.ConnectionConfig.custom()
                .setConnectTimeout(org.apache.hc.core5.util.Timeout.ofSeconds(5))
                .setSocketTimeout(org.apache.hc.core5.util.Timeout.ofSeconds(60))
                .build());
        connPool.setMaxTotal(20);
        connPool.setDefaultMaxPerRoute(10);

        org.apache.hc.client5.http.impl.classic.CloseableHttpClient httpClient =
                org.apache.hc.client5.http.impl.classic.HttpClients.custom()
                        .setConnectionManager(connPool)
                        .build();

        org.springframework.http.client.HttpComponentsClientHttpRequestFactory factory =
                new org.springframework.http.client.HttpComponentsClientHttpRequestFactory(httpClient);
        restTemplate = new RestTemplate(factory);
    }

    // =========================================================================
    // Level 1: Raw HTTP — 纯HTTP往返耗时
    // =========================================================================

    @Test
    @DisplayName("Level 1: Raw HTTP POST /api/v1/execute — 纯HTTP往返")
    void level1_rawHttpLatency() {
        Map<String, Object> payload = Map.of(
                "pipeline_stage", "query_understanding",
                "template_key", "serving-query-understanding",
                "input", Map.of("query", TEST_QUERY),
                "caller_service", "serving"
        );

        // Warm up (establish connection, JVM warmup)
        restTemplate.exchange(BASE_URL + "/api/v1/execute", HttpMethod.POST,
                new HttpEntity<>(payload, jsonHeaders()), MAP_TYPE);

        // Measure 5 calls
        long[] durations = new long[5];
        for (int i = 0; i < 5; i++) {
            long start = System.nanoTime();
            restTemplate.exchange(BASE_URL + "/api/v1/execute", HttpMethod.POST,
                    new HttpEntity<>(payload, jsonHeaders()), MAP_TYPE);
            durations[i] = (System.nanoTime() - start) / 1_000_000;
        }

        printLatencyReport("Level 1: Raw HTTP POST /api/v1/execute", durations);
    }

    // =========================================================================
    // Level 1b: Raw HTTP — 分拆连接建立 vs 数据传输
    // =========================================================================

    @Test
    @DisplayName("Level 1b: Cold vs Warm connection — 连接复用对比")
    void level1b_coldVsWarmConnection() {
        Map<String, Object> payload = Map.of(
                "pipeline_stage", "query_understanding",
                "template_key", "serving-query-understanding",
                "input", Map.of("query", TEST_QUERY),
                "caller_service", "serving"
        );

        // Cold call (fresh RestTemplate, no pooled connection)
        RestTemplate coldClient = new RestTemplate();
        long coldStart = System.nanoTime();
        coldClient.exchange(BASE_URL + "/api/v1/execute", HttpMethod.POST,
                new HttpEntity<>(payload, jsonHeaders()), MAP_TYPE);
        long coldMs = (System.nanoTime() - coldStart) / 1_000_000;

        // Warm call (pooled connection)
        long warmStart = System.nanoTime();
        restTemplate.exchange(BASE_URL + "/api/v1/execute", HttpMethod.POST,
                new HttpEntity<>(payload, jsonHeaders()), MAP_TYPE);
        long warmMs = (System.nanoTime() - warmStart) / 1_000_000;

        System.out.println("=== Cold vs Warm Connection ===");
        System.out.printf("  Cold (new RestTemplate): %d ms%n", coldMs);
        System.out.printf("  Warm (pooled):           %d ms%n", warmMs);
        System.out.printf("  Savings:                 %d ms%n", coldMs - warmMs);
    }

    // =========================================================================
    // Level 2: LlmClient.execute() — HTTP + payload构建 + response返回
    // =========================================================================

    @Test
    @DisplayName("Level 2: LlmClient.execute() — 完整client调用")
    void level2_llmClientExecuteLatency() {
        LlmClient llmClient = new LlmClient(restTemplate, BASE_URL);

        Map<String, Object> input = Map.of("query", TEST_QUERY);

        // Warm up
        llmClient.execute("query_understanding", "serving-query-understanding", input);

        // Measure 5 calls
        long[] durations = new long[5];
        for (int i = 0; i < 5; i++) {
            long start = System.nanoTime();
            Map<String, Object> result = llmClient.execute(
                    "query_understanding", "serving-query-understanding", input);
            durations[i] = (System.nanoTime() - start) / 1_000_000;

            if (i == 0) {
                System.out.println("=== Level 2: LlmClient.execute() response keys ===");
                System.out.println("  top-level keys: " + result.keySet());
            }
        }

        printLatencyReport("Level 2: LlmClient.execute()", durations);
    }

    // =========================================================================
    // Level 2b: LlmClient.execute() vs Raw HTTP — 对比client层开销
    // =========================================================================

    @Test
    @DisplayName("Level 2b: Client overhead = LlmClient.execute() minus Raw HTTP")
    void level2b_clientOverhead() {
        LlmClient llmClient = new LlmClient(restTemplate, BASE_URL);
        Map<String, Object> input = Map.of("query", TEST_QUERY);
        Map<String, Object> payload = Map.of(
                "pipeline_stage", "query_understanding",
                "template_key", "serving-query-understanding",
                "input", input,
                "caller_service", "serving"
        );

        // Warm up both
        restTemplate.exchange(BASE_URL + "/api/v1/execute", HttpMethod.POST,
                new HttpEntity<>(payload, jsonHeaders()), MAP_TYPE);
        llmClient.execute("query_understanding", "serving-query-understanding", input);

        // Measure raw HTTP
        long rawStart = System.nanoTime();
        restTemplate.exchange(BASE_URL + "/api/v1/execute", HttpMethod.POST,
                new HttpEntity<>(payload, jsonHeaders()), MAP_TYPE);
        long rawMs = (System.nanoTime() - rawStart) / 1_000_000;

        // Measure LlmClient
        long clientStart = System.nanoTime();
        llmClient.execute("query_understanding", "serving-query-understanding", input);
        long clientMs = (System.nanoTime() - clientStart) / 1_000_000;

        System.out.println("=== Client Overhead Analysis ===");
        System.out.printf("  Raw HTTP:         %d ms%n", rawMs);
        System.out.printf("  LlmClient:        %d ms%n", clientMs);
        System.out.printf("  Client overhead:  %d ms%n", clientMs - rawMs);
    }

    // =========================================================================
    // Level 3: QueryUnderstandingEngine.understand() — 完整理解流程
    // =========================================================================

    @Test
    @DisplayName("Level 3: QueryUnderstandingEngine.understand() — 完整QU流程")
    void level3_quEngineLatency() {
        LlmClient llmClient = new LlmClient(restTemplate, BASE_URL);
        QueryUnderstandingEngine engine = new QueryUnderstandingEngine(llmClient);

        // Warm up
        engine.understand(TEST_QUERY, null);

        // Measure 5 calls
        long[] durations = new long[5];
        QueryUnderstanding lastResult = null;
        for (int i = 0; i < 5; i++) {
            long start = System.nanoTime();
            lastResult = engine.understand(TEST_QUERY, null);
            durations[i] = (System.nanoTime() - start) / 1_000_000;
        }

        printLatencyReport("Level 3: QueryUnderstandingEngine.understand()", durations);

        System.out.println("\n=== QU Result ===");
        System.out.println("  source: " + lastResult.source());
        System.out.println("  intent: " + lastResult.intent());
        System.out.println("  entities: " + lastResult.entities().size());
        System.out.println("  keywords: " + lastResult.keywords());
    }

    // =========================================================================
    // Level 3b: 分拆QU内部子步骤
    // =========================================================================

    @Test
    @DisplayName("Level 3b: QU内部步骤拆解 — execute vs unwrap vs parse")
    void level3b_quInternalBreakdown() {
        LlmClient llmClient = new LlmClient(restTemplate, BASE_URL);
        Map<String, Object> input = Map.of("query", TEST_QUERY);

        // Warm up
        llmClient.execute("query_understanding", "serving-query-understanding", input);

        int iterations = 5;
        long[] executeMs = new long[iterations];
        long[] unwrapMs = new long[iterations];
        long[] parseMs = new long[iterations];

        for (int i = 0; i < iterations; i++) {
            // Step A: LlmClient.execute()
            long t0 = System.nanoTime();
            Map<String, Object> result = llmClient.execute(
                    "query_understanding", "serving-query-understanding", input);
            long t1 = System.nanoTime();

            // Step B: unwrapResponse()
            Map<String, Object> data = LlmClient.unwrapResponse(result);
            long t2 = System.nanoTime();

            // Step C: parse (drill into data.result.parsed_output)
            Object resultObj = data.getOrDefault("result", data);
            @SuppressWarnings("unchecked")
            Map<String, Object> inner = (resultObj instanceof Map) ? (Map<String, Object>) resultObj : Map.of();
            @SuppressWarnings("unchecked")
            Map<String, Object> parsed = (Map<String, Object>) inner.getOrDefault("parsed_output", Map.of());
            long t3 = System.nanoTime();

            executeMs[i] = (t1 - t0) / 1_000_000;
            unwrapMs[i] = (t2 - t1) / 1_000_000;
            parseMs[i] = (t3 - t2) / 1_000_000;
        }

        System.out.println("=== Level 3b: QU Internal Step Breakdown (avg of " + iterations + ") ===");
        System.out.printf("  A. LlmClient.execute():  avg=%6.1f ms  %s%n",
                avg(executeMs), formatArray(executeMs));
        System.out.printf("  B. unwrapResponse():      avg=%6.1f ms  %s%n",
                avg(unwrapMs), formatArray(unwrapMs));
        System.out.printf("  C. parse parsed_output:   avg=%6.1f ms  %s%n",
                avg(parseMs), formatArray(parseMs));
        System.out.printf("  Total:                    avg=%6.1f ms%n",
                avg(executeMs) + avg(unwrapMs) + avg(parseMs));
    }

    // =========================================================================
    // Level 4: Embedding + Understanding 并行 vs 串行
    // =========================================================================

    @Test
    @DisplayName("Level 4: Embedding + Understanding 并行 vs 串行对比")
    void level4_parallelVsSequential() {
        LlmClient llmClient = new LlmClient(restTemplate, BASE_URL);
        QueryUnderstandingEngine engine = new QueryUnderstandingEngine(llmClient);
        EmbeddingClient embeddingClient = new EmbeddingClient(llmClient);

        // Warm up
        engine.understand(TEST_QUERY, null);
        embeddingClient.embed(TEST_QUERY);

        // Sequential
        long seqStart = System.nanoTime();
        QueryUnderstanding seqUnderstanding = engine.understand(TEST_QUERY, null);
        float[] seqEmbedding = embeddingClient.embed(TEST_QUERY);
        long seqMs = (System.nanoTime() - seqStart) / 1_000_000;

        // Parallel (virtual threads)
        long parStart = System.nanoTime();
        CompletableFuture<QueryUnderstanding> understandingFuture = CompletableFuture.supplyAsync(
                () -> engine.understand(TEST_QUERY, null));
        CompletableFuture<float[]> embeddingFuture = CompletableFuture.supplyAsync(
                () -> embeddingClient.embed(TEST_QUERY));
        QueryUnderstanding parUnderstanding = understandingFuture.join();
        float[] parEmbedding = embeddingFuture.join();
        long parMs = (System.nanoTime() - parStart) / 1_000_000;

        System.out.println("=== Level 4: Parallel vs Sequential ===");
        System.out.printf("  Sequential: %d ms%n", seqMs);
        System.out.printf("  Parallel:   %d ms%n", parMs);
        System.out.printf("  Saved:      %d ms%n", seqMs - parMs);
        System.out.printf("  Understanding source: %s%n", parUnderstanding.source());
        System.out.printf("  Embedding dim: %d%n", parEmbedding.length);
    }

    // =========================================================================
    // Level 5: 完整pipeline模拟 (SearchService级别)
    // =========================================================================

    @Test
    @DisplayName("Level 5: Full pipeline stages latency — 完整流水线各阶段耗时")
    void level5_fullPipelineStages() {
        LlmClient llmClient = new LlmClient(restTemplate, BASE_URL);
        QueryUnderstandingEngine engine = new QueryUnderstandingEngine(llmClient);
        EmbeddingClient embeddingClient = new EmbeddingClient(llmClient);

        // Warm up all stages
        engine.understand(TEST_QUERY, null);
        embeddingClient.embed(TEST_QUERY);
        // Warm up rerank
        llmClient.rerank(TEST_QUERY, List.of("SMF是会话管理功能", "UPF是用户面功能"), 2);

        System.out.println("=== Level 5: Full Pipeline Stages (5 iterations) ===");

        for (int i = 0; i < 5; i++) {
            long t0, t1, t2, t3, t4;

            // Stage 1: Query Understanding
            t0 = System.nanoTime();
            QueryUnderstanding understanding = engine.understand(TEST_QUERY, null);
            t1 = System.nanoTime();
            long quMs = (t1 - t0) / 1_000_000;

            // Stage 2: Embedding (parallel in production, but sequential here for measurement)
            t1 = System.nanoTime();
            float[] embedding = embeddingClient.embed(TEST_QUERY);
            t2 = System.nanoTime();
            long embMs = (t2 - t1) / 1_000_000;

            // Stage 3: Rerank (simulated with dummy documents)
            List<String> docs = List.of(
                    "SMF是会话管理功能，负责PDU会话管理",
                    "UPF是用户面功能，负责数据转发",
                    "AMF是接入和移动性管理功能"
            );
            t3 = System.nanoTime();
            Map<String, Object> rerankResult = llmClient.rerank(TEST_QUERY, docs, 3);
            t4 = System.nanoTime();
            long rerankMs = (t4 - t3) / 1_000_000;

            long total = (t4 - t0) / 1_000_000;
            System.out.printf("  [%d] QU=%dms  Embed=%dms  Rerank=%dms  Total=%dms%n",
                    i + 1, quMs, embMs, rerankMs, total);
        }
    }

    // =========================================================================
    // Level 6: RestTemplate序列化/反序列化开销隔离测试
    // =========================================================================

    @Test
    @DisplayName("Level 6: JVM warmup impact — 前3次 vs 后3次对比")
    void level6_jvmWarmupImpact() {
        LlmClient llmClient = new LlmClient(restTemplate, BASE_URL);
        Map<String, Object> input = Map.of("query", TEST_QUERY);

        long[] allDurations = new long[10];
        for (int i = 0; i < 10; i++) {
            long start = System.nanoTime();
            llmClient.execute("query_understanding", "serving-query-understanding", input);
            allDurations[i] = (System.nanoTime() - start) / 1_000_000;
        }

        System.out.println("=== Level 6: JVM Warmup Impact ===");
        System.out.printf("  First 3: avg=%6.1f ms  %s%n",
                avg(allDurations, 0, 3), formatArray(allDurations, 0, 3));
        System.out.printf("  Last  3: avg=%6.1f ms  %s%n",
                avg(allDurations, 7, 3), formatArray(allDurations, 7, 3));
        System.out.printf("  Warmup cost: %.1f ms%n",
                avg(allDurations, 0, 3) - avg(allDurations, 7, 3));

        System.out.println("\n  All 10 calls:");
        for (int i = 0; i < 10; i++) {
            System.out.printf("    [%2d] %d ms%n", i + 1, allDurations[i]);
        }
    }

    // =========================================================================
    // Helpers
    // =========================================================================

    private static final ParameterizedTypeReference<Map<String, Object>> MAP_TYPE =
            new ParameterizedTypeReference<>() {};

    private static HttpHeaders jsonHeaders() {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        return headers;
    }

    private static void printLatencyReport(String title, long[] durations) {
        System.out.println("\n=== " + title + " (" + durations.length + " calls) ===");
        for (int i = 0; i < durations.length; i++) {
            System.out.printf("  [%d] %d ms%n", i + 1, durations[i]);
        }
        System.out.printf("  Avg: %.1f ms%n", avg(durations));
        System.out.printf("  Min: %d ms%n", min(durations));
        System.out.printf("  Max: %d ms%n", max(durations));
        System.out.printf("  P50: %.1f ms%n", percentile(durations, 50));
        System.out.printf("  P90: %.1f ms%n", percentile(durations, 90));
    }

    private static double avg(long[] arr) {
        long sum = 0;
        for (long v : arr) sum += v;
        return (double) sum / arr.length;
    }

    private static double avg(long[] arr, int start, int count) {
        long sum = 0;
        for (int i = start; i < start + count; i++) sum += arr[i];
        return (double) sum / count;
    }

    private static long min(long[] arr) {
        long m = arr[0];
        for (long v : arr) if (v < m) m = v;
        return m;
    }

    private static long max(long[] arr) {
        long m = arr[0];
        for (long v : arr) if (v > m) m = v;
        return m;
    }

    private static double percentile(long[] arr, int pct) {
        long[] sorted = arr.clone();
        java.util.Arrays.sort(sorted);
        int idx = (int) Math.ceil(pct / 100.0 * sorted.length) - 1;
        return sorted[Math.max(0, idx)];
    }

    private static String formatArray(long[] arr) {
        return formatArray(arr, 0, arr.length);
    }

    private static String formatArray(long[] arr, int start, int count) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = start; i < start + count; i++) {
            if (i > start) sb.append(", ");
            sb.append(arr[i]);
        }
        return sb.append("]").toString();
    }
}
