package com.coremasterkb.serving.client;

import com.coremasterkb.serving.config.ServingProperties;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.*;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Direct client for Zhipu AI API (https://open.bigmodel.cn/api/paas/v4).
 *
 * Embedding endpoint: POST /embeddings
 * Request:  {"model": "embedding-3", "input": "...", "dimensions": 2048}
 * Response: {"data": [{"embedding": [0.1, ...], "index": 0, "object": "embedding"}], ...}
 */
public class ZhipuClient {

    private static final Logger log = LoggerFactory.getLogger(ZhipuClient.class);

    private static final int CONNECT_TIMEOUT_MS = 5_000;
    private static final int READ_TIMEOUT_MS    = 30_000;

    private final ServingProperties.Zhipu config;
    private final RestTemplate restTemplate;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public ZhipuClient(ServingProperties.Zhipu config) {
        this.config = config;
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(CONNECT_TIMEOUT_MS);
        factory.setReadTimeout(READ_TIMEOUT_MS);
        this.restTemplate = new RestTemplate(factory);
    }

    /**
     * Embed a single text string.
     *
     * @return float array of length {@code config.embeddingDimensions},
     *         or empty array on any error
     */
    @SuppressWarnings("unchecked")
    public float[] embed(String text) {
        if (text == null || text.isBlank()) return new float[0];

        try {
            Map<String, Object> body = new HashMap<>();
            body.put("model", config.getEmbeddingModel());
            body.put("input", text);
            body.put("dimensions", config.getEmbeddingDimensions());

            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            headers.set("Authorization", "Bearer " + config.getApiKey());

            String requestBody = objectMapper.writeValueAsString(body);
            HttpEntity<String> entity = new HttpEntity<>(requestBody, headers);

            String url = config.getBaseUrl() + "/embeddings";
            ResponseEntity<String> response =
                    restTemplate.exchange(url, HttpMethod.POST, entity, String.class);

            if (!response.getStatusCode().is2xxSuccessful() || response.getBody() == null) {
                log.debug("Zhipu embed returned non-2xx: {}", response.getStatusCode());
                return new float[0];
            }

            Map<String, Object> parsed = objectMapper.readValue(
                    response.getBody(), new TypeReference<>() {});

            // data[0].embedding
            Object data = parsed.get("data");
            if (!(data instanceof List<?> dataList) || dataList.isEmpty()) return new float[0];
            Object first = dataList.get(0);
            if (!(first instanceof Map<?, ?> firstMap)) return new float[0];
            Object embeddingRaw = ((Map<String, Object>) firstMap).get("embedding");
            if (!(embeddingRaw instanceof List<?> embList)) return new float[0];

            float[] result = new float[embList.size()];
            for (int i = 0; i < embList.size(); i++) {
                result[i] = ((Number) embList.get(i)).floatValue();
            }
            return result;

        } catch (Exception e) {
            log.debug("Zhipu embed failed: {}", e.getMessage());
            return new float[0];
        }
    }

    /** Batch embed — convenience wrapper; returns empty list on error. */
    public List<float[]> embedBatch(List<String> texts) {
        if (texts == null || texts.isEmpty()) {
            return Collections.emptyList();
        }
        return texts.stream()
                .map(this::embed)
                .toList();
    }

    /**
     * Rerank documents against a query.
     *
     * Endpoint: POST /rerank
     * Request:  {"model": "rerank", "query": "...", "documents": [...], "top_n": N}
     * Response: {"results": [{"index": 0, "relevance_score": 0.95, "document": {...}}, ...]}
     *
     * @return list of result maps with keys "index" (Integer) and "score" (Double),
     *         ordered by relevance descending; empty list on any error / not configured
     */
    @SuppressWarnings("unchecked")
    public List<Map<String, Object>> rerank(String query, List<String> documents, int topN) {
        if (query == null || query.isBlank() || documents == null || documents.isEmpty()) {
            return Collections.emptyList();
        }

        try {
            Map<String, Object> body = new HashMap<>();
            body.put("model", config.getRerankModel());
            body.put("query", query);
            body.put("documents", documents);
            body.put("top_n", topN);

            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            headers.set("Authorization", "Bearer " + config.getApiKey());

            String requestBody = objectMapper.writeValueAsString(body);
            HttpEntity<String> entity = new HttpEntity<>(requestBody, headers);

            String url = config.getBaseUrl() + "/rerank";
            ResponseEntity<String> response =
                    restTemplate.exchange(url, HttpMethod.POST, entity, String.class);

            if (!response.getStatusCode().is2xxSuccessful() || response.getBody() == null) {
                log.debug("Zhipu rerank returned non-2xx: {}", response.getStatusCode());
                return Collections.emptyList();
            }

            Map<String, Object> parsed = objectMapper.readValue(
                    response.getBody(), new TypeReference<>() {});

            Object resultsRaw = parsed.get("results");
            if (!(resultsRaw instanceof List<?> rawList)) return Collections.emptyList();

            // Normalize to {index, score} maps (callers expect "score", not "relevance_score")
            List<Map<String, Object>> out = new ArrayList<>();
            for (Object item : rawList) {
                if (!(item instanceof Map<?, ?> m)) continue;
                Map<String, Object> r = (Map<String, Object>) m;
                Object idxObj   = r.get("index");
                Object scoreObj = r.get("relevance_score");
                if (idxObj instanceof Number && scoreObj instanceof Number) {
                    Map<String, Object> entry = new HashMap<>();
                    entry.put("index", ((Number) idxObj).intValue());
                    entry.put("score", ((Number) scoreObj).doubleValue());
                    out.add(entry);
                }
            }
            return out;

        } catch (Exception e) {
            log.debug("Zhipu rerank failed: {}", e.getMessage());
            return Collections.emptyList();
        }
    }
}
