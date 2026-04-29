package com.coremasterkb.serving.client;

import com.coremasterkb.serving.config.ServingProperties;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.*;
import org.springframework.web.client.RestTemplate;

import java.util.Collections;
import java.util.Map;

/**
 * HTTP client for the optional LLM runtime service.
 * When disabled or unreachable, all methods return empty/false results
 * so the calling code falls back to rule-based logic transparently.
 */
public class LlmRuntimeClient {

    private static final Logger log = LoggerFactory.getLogger(LlmRuntimeClient.class);

    private final ServingProperties.LlmService config;
    private final RestTemplate restTemplate;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public LlmRuntimeClient(ServingProperties.LlmService config) {
        this.config = config;
        this.restTemplate = buildRestTemplate(
                (int) config.getConnectTimeout().toMillis(),
                (int) config.getReadTimeout().toMillis());
    }

    // -------------------------------------------------------------------------
    // Public API
    // -------------------------------------------------------------------------

    /**
     * Returns true only when the LLM service is enabled and responds to /health.
     */
    public boolean isAvailable() {
        if (!config.isEnabled()) return false;
        try {
            ResponseEntity<String> resp =
                    restTemplate.getForEntity(config.getBaseUrl() + "/health", String.class);
            return resp.getStatusCode().is2xxSuccessful();
        } catch (Exception e) {
            log.debug("LLM service health check failed: {}", e.getMessage());
            return false;
        }
    }

    /**
     * Synchronous task execution: POST {baseUrl}/api/v1/execute.
     *
     * @param payload request body
     * @return parsed response map, or empty map on any error
     */
    public Map<String, Object> execute(Map<String, Object> payload) {
        if (!config.isEnabled()) return Collections.emptyMap();
        try {
            return post(config.getBaseUrl() + "/api/v1/execute", payload);
        } catch (Exception e) {
            log.debug("LLM execute failed: {}", e.getMessage());
            return Collections.emptyMap();
        }
    }

    /**
     * Async task submission: POST {baseUrl}/api/v1/tasks.
     */
    public Map<String, Object> submitTask(Map<String, Object> payload) {
        if (!config.isEnabled()) return Collections.emptyMap();
        try {
            return post(config.getBaseUrl() + "/api/v1/tasks", payload);
        } catch (Exception e) {
            log.debug("LLM submitTask failed: {}", e.getMessage());
            return Collections.emptyMap();
        }
    }

    /**
     * Embed text: POST {baseUrl}/api/v1/embed.
     * Expected response: {"embedding": [0.1, 0.2, ...]}
     *
     * @return float array of the embedding, or empty array on any error
     */
    @SuppressWarnings("unchecked")
    public float[] embed(String text) {
        if (!config.isEnabled()) return new float[0];
        try {
            Map<String, Object> payload = new java.util.HashMap<>();
            payload.put("caller_domain", "serving");
            payload.put("pipeline_stage", "dense_retrieval");
            payload.put("text", text);
            Map<String, Object> resp = post(config.getBaseUrl() + "/api/v1/embed", payload);
            Object embedding = resp.get("embedding");
            if (embedding instanceof java.util.List<?> list) {
                float[] result = new float[list.size()];
                for (int i = 0; i < list.size(); i++) {
                    result[i] = ((Number) list.get(i)).floatValue();
                }
                return result;
            }
            return new float[0];
        } catch (Exception e) {
            log.debug("LLM embed failed: {}", e.getMessage());
            return new float[0];
        }
    }

    /**
     * Rerank documents: POST {baseUrl}/api/v1/rerank.
     * Expected response: {"results": [{"index": 0, "score": 0.95}, ...]}
     *
     * @return list of result maps, or empty list on any error
     */
    @SuppressWarnings("unchecked")
    public java.util.List<Map<String, Object>> rerank(
            String query, java.util.List<String> documents, int topN) {
        if (!config.isEnabled()) return Collections.emptyList();
        try {
            Map<String, Object> payload = new java.util.HashMap<>();
            payload.put("caller_domain", "serving");
            payload.put("pipeline_stage", "rerank");
            payload.put("query", query);
            payload.put("documents", documents);
            payload.put("top_n", topN);
            Map<String, Object> resp = post(config.getBaseUrl() + "/api/v1/rerank", payload);
            Object results = resp.get("results");
            if (results instanceof java.util.List<?> list) {
                java.util.List<Map<String, Object>> out = new java.util.ArrayList<>();
                for (Object item : list) {
                    if (item instanceof Map<?, ?> m) {
                        out.add((Map<String, Object>) m);
                    }
                }
                return out;
            }
            return Collections.emptyList();
        } catch (Exception e) {
            log.debug("LLM rerank failed: {}", e.getMessage());
            return Collections.emptyList();
        }
    }

    // -------------------------------------------------------------------------
    // Internals
    // -------------------------------------------------------------------------

    private Map<String, Object> post(String url, Map<String, Object> payload) throws Exception {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        String body = objectMapper.writeValueAsString(payload);
        HttpEntity<String> request = new HttpEntity<>(body, headers);

        ResponseEntity<String> resp = restTemplate.exchange(
                url, HttpMethod.POST, request, String.class);

        if (resp.getStatusCode().is2xxSuccessful() && resp.getBody() != null) {
            return objectMapper.readValue(resp.getBody(), new TypeReference<>() {});
        }
        return Collections.emptyMap();
    }

    private RestTemplate buildRestTemplate(int connectTimeoutMillis, int readTimeoutMillis) {
        org.springframework.http.client.SimpleClientHttpRequestFactory factory =
                new org.springframework.http.client.SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(connectTimeoutMillis);
        factory.setReadTimeout(readTimeoutMillis);
        return new RestTemplate(factory);
    }
}
