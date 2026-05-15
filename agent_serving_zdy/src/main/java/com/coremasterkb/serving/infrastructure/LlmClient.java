package com.coremasterkb.serving.infrastructure;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.*;
import org.springframework.web.client.RestTemplate;

import java.util.*;
import java.util.concurrent.atomic.AtomicLong;

public class LlmClient {

    private static final Logger log = LoggerFactory.getLogger(LlmClient.class);
    private static final long HEALTH_CACHE_TTL_MS = 30_000;
    private static final ParameterizedTypeReference<Map<String, Object>> MAP_TYPE =
            new ParameterizedTypeReference<>() {};

    private final RestTemplate restTemplate;
    private final String baseUrl;

    // Health check cache
    private final AtomicLong lastHealthCheckMs = new AtomicLong(0);
    private volatile boolean cachedHealth = false;

    public LlmClient(RestTemplate restTemplate, String baseUrl) {
        this.restTemplate = restTemplate;
        this.baseUrl = baseUrl != null ? baseUrl.replaceAll("/+$", "") : null;
    }

    // =========================================================================
    // Availability
    // =========================================================================

    public boolean isAvailable() {
        if (baseUrl == null || baseUrl.isBlank()) {
            return false;
        }
        long now = System.currentTimeMillis();
        long last = lastHealthCheckMs.get();
        if (now - last < HEALTH_CACHE_TTL_MS) {
            return cachedHealth;
        }
        boolean healthy = checkHealth();
        cachedHealth = healthy;
        lastHealthCheckMs.set(now);
        return healthy;
    }

    public boolean checkHealth() {
        try {
            ResponseEntity<Map<String, Object>> response = restTemplate.exchange(
                    baseUrl + "/health",
                    HttpMethod.GET,
                    new HttpEntity<>(buildHeaders()),
                    MAP_TYPE
            );
            return response.getStatusCode().is2xxSuccessful();
        } catch (Exception e) {
            log.debug("LLM health check failed: {}", e.getMessage());
            return false;
        }
    }

    // =========================================================================
    // Execute (template-based LLM call)
    // =========================================================================

    public Map<String, Object> execute(String pipelineStage, String templateKey, Map<String, Object> input) {
        if (!isAvailable()) {
            throw new IllegalStateException("LLM client not configured");
        }

        Map<String, Object> payload = new HashMap<>();
        payload.put("pipeline_stage", pipelineStage);
        payload.put("template_key", templateKey);
        payload.put("input", input);
        payload.put("caller_domain", "serving");

        ResponseEntity<Map<String, Object>> response = restTemplate.exchange(
                baseUrl + "/api/v1/execute",
                HttpMethod.POST,
                new HttpEntity<>(payload, buildHeaders()),
                MAP_TYPE);
        return response.getBody() != null ? response.getBody() : Map.of();
    }

    // =========================================================================
    // Embeddings
    // =========================================================================

    public Map<String, Object> embed(List<String> texts, String model, Integer dimensions) {
        if (!isAvailable()) {
            throw new IllegalStateException("LLM client not configured");
        }

        Map<String, Object> payload = new HashMap<>();
        payload.put("input", texts);
        if (model != null) payload.put("model", model);
        if (dimensions != null) payload.put("dimensions", dimensions);

        ResponseEntity<Map<String, Object>> response = restTemplate.exchange(
                baseUrl + "/api/v1/models/embeddings",
                HttpMethod.POST,
                new HttpEntity<>(payload, buildHeaders()),
                MAP_TYPE);
        return response.getBody() != null ? response.getBody() : Map.of();
    }

    // =========================================================================
    // Rerank
    // =========================================================================

    public Map<String, Object> rerank(String query, List<String> documents, String model, Integer topN) {
        if (!isAvailable()) {
            throw new IllegalStateException("LLM client not configured");
        }

        Map<String, Object> payload = new HashMap<>();
        payload.put("query", query);
        payload.put("documents", documents);
        if (model != null) payload.put("model", model);
        if (topN != null) payload.put("top_n", topN);

        ResponseEntity<Map<String, Object>> response = restTemplate.exchange(
                baseUrl + "/api/v1/models/rerank",
                HttpMethod.POST,
                new HttpEntity<>(payload, buildHeaders()),
                MAP_TYPE);
        return response.getBody() != null ? response.getBody() : Map.of();
    }

    // =========================================================================
    // Template registration
    // =========================================================================

    public void ensureTemplates() {
        if (!isAvailable()) {
            log.info("LLM service not available, skipping template registration");
            return;
        }
        for (var tpl : ServingTemplates.ALL) {
            try {
                Map<String, Object> payload = new HashMap<>(tpl);
                String schemaStr = (String) payload.getOrDefault("output_schema_json", "");
                String exampleStr = (String) payload.remove("_example_json");
                String systemPrompt = (String) payload.get("system_prompt");
                if (systemPrompt != null) {
                    payload.put("system_prompt",
                            systemPrompt.replace("{output_schema}", schemaStr)
                                        .replace("{example}", exampleStr != null ? exampleStr : ""));
                }

                ResponseEntity<Map<String, Object>> response = restTemplate.exchange(
                        baseUrl + "/api/v1/templates",
                        HttpMethod.POST,
                        new HttpEntity<>(payload, buildHeaders()),
                        MAP_TYPE);

                HttpStatusCode status = response.getStatusCode();
                if (status.is2xxSuccessful() || status == HttpStatus.CONFLICT) {
                    log.info("Registered template: {}", tpl.get("template_key"));
                } else {
                    log.warn("Failed to register template '{}': HTTP {}",
                            tpl.get("template_key"), status);
                }
            } catch (Exception e) {
                log.warn("Failed to register template '{}': {}", tpl.get("template_key"), e.getMessage());
            }
        }
    }

    // =========================================================================
    // Internal
    // =========================================================================

    private HttpHeaders buildHeaders() {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        return headers;
    }
}
