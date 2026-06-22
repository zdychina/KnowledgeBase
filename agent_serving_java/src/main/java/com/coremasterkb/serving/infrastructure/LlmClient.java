package com.coremasterkb.serving.infrastructure;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.*;
import org.springframework.web.client.RestTemplate;

import java.util.*;

/**
 * Client for the shared LLM service (llm_service).
 *
 * <p>Supports:
 * <ul>
 *   <li>{@code execute} — template-based LLM calls via POST /api/v1/execute</li>
 *   <li>{@code embed} — text embedding via POST /api/v1/models/embeddings</li>
 *   <li>{@code rerank} — model rerank via POST /api/v1/models/rerank</li>
 *   <li>Template registration via POST /api/v1/templates (at startup)</li>
 * </ul>
 *
 * <p>No health-check probing — availability is determined by baseUrl being configured.
 * Call failures are surfaced as exceptions and handled by callers (fallback, retry, etc.).
 */
public class LlmClient {

    private static final Logger log = LoggerFactory.getLogger(LlmClient.class);
    private static final ParameterizedTypeReference<Map<String, Object>> MAP_TYPE =
            new ParameterizedTypeReference<>() {};

    private final RestTemplate restTemplate;
    private final String baseUrl;
    private final ThreadLocal<String> domainHolder = new ThreadLocal<>();

    public LlmClient(RestTemplate restTemplate, String baseUrl) {
        this.restTemplate = restTemplate;
        this.baseUrl = baseUrl != null ? baseUrl.replaceAll("/+$", "") : null;
    }

    /** Set the knowledge domain for billing and audit in llm_service. */
    public void setKnowledgeDomain(String domain) {
        this.domainHolder.set(domain);
    }

    /** Clear the thread-local domain (call in finally block). */
    public void clearKnowledgeDomain() {
        this.domainHolder.remove();
    }

    private String getKnowledgeDomain() {
        return this.domainHolder.get();
    }

    // =========================================================================
    // Availability — lightweight check (no HTTP call)
    // =========================================================================

    /**
     * Returns true if the client has a non-blank baseUrl configured.
     * No HTTP health-check is performed — call failures are handled by callers.
     */
    public boolean isAvailable() {
        return baseUrl != null && !baseUrl.isBlank();
    }

    // =========================================================================
    // Execute (template-based LLM call)
    // =========================================================================

    public Map<String, Object> execute(String pipelineStage, String templateKey, Map<String, Object> input) {
        Map<String, Object> payload = new HashMap<>();
        payload.put("pipeline_stage", pipelineStage);
        payload.put("template_key", templateKey);
        payload.put("input", input);
        payload.put("caller_service", "serving");
        if (getKnowledgeDomain() != null && !getKnowledgeDomain().isBlank()) {
            payload.put("knowledge_domain", getKnowledgeDomain());
        }

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

    /**
     * Call the embedding endpoint.
     * Model and dimensions are managed by llm_service — callers only provide texts.
     */
    public Map<String, Object> embed(List<String> texts) {
        Map<String, Object> payload = new HashMap<>();
        payload.put("input", texts);
        payload.put("caller_service", "serving");
        if (getKnowledgeDomain() != null && !getKnowledgeDomain().isBlank()) {
            payload.put("knowledge_domain", getKnowledgeDomain());
        }

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

    /**
     * Call the rerank endpoint.
     * Model is managed by llm_service — callers only provide query, documents, and optional topN.
     */
    public Map<String, Object> rerank(String query, List<String> documents, Integer topN) {
        Map<String, Object> payload = new HashMap<>();
        payload.put("query", query);
        payload.put("documents", documents);
        if (topN != null) payload.put("top_n", topN);
        payload.put("caller_service", "serving");
        if (getKnowledgeDomain() != null && !getKnowledgeDomain().isBlank()) {
            payload.put("knowledge_domain", getKnowledgeDomain());
        }

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

    /**
     * Retry template registration with exponential backoff.
     * Called from a background thread at startup — waits for llm_service to become available.
     * Retries up to 10 times (total ~2 min), then gives up.
     */
    public void ensureTemplatesWithRetry(String targetUrl) {
        int maxAttempts = 10;
        long baseDelayMs = 3_000;

        for (int attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
                // Probe health endpoint first
                restTemplate.exchange(
                        targetUrl + "/health",
                        HttpMethod.GET,
                        new HttpEntity<>(buildHeaders()),
                        MAP_TYPE);
                // Health OK — register templates
                ensureTemplates();
                return;
            } catch (Exception e) {
                long delay = baseDelayMs * (1L << Math.min(attempt - 1, 4)); // 3s, 6s, 12s, 24s, 48s, ...
                if (attempt < maxAttempts) {
                    log.info("LLM service not ready (attempt {}/{}), retrying in {}ms: {}",
                            attempt, maxAttempts, delay, e.getMessage());
                    try { Thread.sleep(delay); } catch (InterruptedException ie) {
                        Thread.currentThread().interrupt();
                        log.warn("Template registration interrupted");
                        return;
                    }
                } else {
                    log.error("LLM service still not available after {} attempts — template registration FAILED", maxAttempts);
                }
            }
        }
    }

    public void ensureTemplates() {
        for (var tpl : ServingTemplates.ALL) {
            try {
                Map<String, Object> payload = new HashMap<>(tpl);
                // DB column is JSON type — empty string is invalid, default to "{}"
                String schemaStr = (String) payload.getOrDefault("output_schema_json", "{}");
                if (schemaStr.isBlank()) schemaStr = "{}";
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
    // Response unwrapping
    // =========================================================================

    /**
     * Unwrap llm_service response envelope.
     * llm_service returns: {@code {success: true, data: {...}}}
     * The actual payload is inside {@code data}.
     *
     * @return the unwrapped payload, or the original body if no envelope detected
     */
    @SuppressWarnings("unchecked")
    public static Map<String, Object> unwrapResponse(Map<String, Object> body) {
        if (body == null) return Map.of();
        // If body has "data" key, unwrap it
        Object dataObj = body.get("data");
        if (dataObj instanceof Map<?, ?> m) {
            return (Map<String, Object>) m;
        }
        return body;
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
