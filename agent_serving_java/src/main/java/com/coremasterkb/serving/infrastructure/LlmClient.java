package com.coremasterkb.serving.infrastructure;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.*;
import org.springframework.web.client.RestTemplate;

import java.util.*;
import java.util.concurrent.atomic.AtomicLong;

public class LlmClient {

    private static final Logger log = LoggerFactory.getLogger(LlmClient.class);
    private static final long HEALTH_CACHE_TTL_MS = 30_000;

    private final RestTemplate restTemplate;
    private final String baseUrl;
    private final String apiKey;

    // Health check cache
    private final AtomicLong lastHealthCheckMs = new AtomicLong(0);
    private volatile boolean cachedHealth = false;

    public LlmClient(RestTemplate restTemplate, String baseUrl, String apiKey) {
        this.restTemplate = restTemplate;
        this.baseUrl = baseUrl != null ? baseUrl.replaceAll("/+$", "") : null;
        this.apiKey = apiKey;
    }

    // =========================================================================
    // Availability
    // =========================================================================

    public boolean isAvailable() {
        if (baseUrl == null || baseUrl.isBlank() || apiKey == null || apiKey.isBlank()) {
            return false;
        }
        // Use cached health result within TTL
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
            HttpHeaders headers = buildHeaders();
            ResponseEntity<Map> response = restTemplate.exchange(
                    baseUrl + "/health",
                    HttpMethod.GET,
                    new HttpEntity<>(headers),
                    Map.class
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

        HttpHeaders headers = buildHeaders();
        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(payload, headers);
        ResponseEntity<Map> response = restTemplate.postForEntity(
                baseUrl + "/api/v1/execute", entity, Map.class);
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

        HttpHeaders headers = buildHeaders();
        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(payload, headers);
        ResponseEntity<Map> response = restTemplate.postForEntity(
                baseUrl + "/api/v1/models/embeddings", entity, Map.class);
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

        HttpHeaders headers = buildHeaders();
        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(payload, headers);
        ResponseEntity<Map> response = restTemplate.postForEntity(
                baseUrl + "/api/v1/models/rerank", entity, Map.class);
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
                // Resolve placeholders in system_prompt
                Map<String, Object> payload = new HashMap<>(tpl);
                String schemaStr = (String) payload.getOrDefault("output_schema_json", "");
                String exampleStr = (String) payload.remove("_example_json");
                String systemPrompt = (String) payload.get("system_prompt");
                if (systemPrompt != null) {
                    payload.put("system_prompt",
                            systemPrompt.replace("{output_schema}", schemaStr)
                                        .replace("{example}", exampleStr != null ? exampleStr : ""));
                }

                HttpHeaders headers = buildHeaders();
                HttpEntity<Map<String, Object>> entity = new HttpEntity<>(payload, headers);
                ResponseEntity<Map> response = restTemplate.postForEntity(
                        baseUrl + "/api/v1/templates", entity, Map.class);

                if (response.getStatusCode().is2xxSuccessful()
                        || response.getStatusCode() == HttpStatus.CREATED
                        || response.getStatusCode() == HttpStatus.CONFLICT) {
                    log.info("Registered template: {}", tpl.get("template_key"));
                } else {
                    log.warn("Failed to register template {}: HTTP {}",
                            tpl.get("template_key"), response.getStatusCode());
                }
            } catch (Exception e) {
                log.warn("Failed to register template: {}", tpl.get("template_key"));
            }
        }
    }

    // =========================================================================
    // Internal
    // =========================================================================

    private HttpHeaders buildHeaders() {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        if (apiKey != null && !apiKey.isBlank()) {
            headers.setBearerAuth(apiKey);
        }
        return headers;
    }
}
