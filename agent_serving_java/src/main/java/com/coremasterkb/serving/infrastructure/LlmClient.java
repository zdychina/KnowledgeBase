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
    private volatile String knowledgeDomain;

    public LlmClient(RestTemplate restTemplate, String baseUrl) {
        this.restTemplate = restTemplate;
        this.baseUrl = baseUrl != null ? baseUrl.replaceAll("/+$", "") : null;
    }

    /** Set the knowledge domain for billing and audit in llm_service. */
    public void setKnowledgeDomain(String domain) {
        this.knowledgeDomain = domain;
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
        if (knowledgeDomain != null && !knowledgeDomain.isBlank()) {
            payload.put("knowledge_domain", knowledgeDomain);
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

    public Map<String, Object> embed(List<String> texts, String model, Integer dimensions) {
        Map<String, Object> payload = new HashMap<>();
        payload.put("input", texts);
        if (model != null) payload.put("model", model);
        if (dimensions != null) payload.put("dimensions", dimensions);
        payload.put("caller_service", "serving");
        if (knowledgeDomain != null && !knowledgeDomain.isBlank()) {
            payload.put("knowledge_domain", knowledgeDomain);
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

    public Map<String, Object> rerank(String query, List<String> documents, String model, Integer topN) {
        Map<String, Object> payload = new HashMap<>();
        payload.put("query", query);
        payload.put("documents", documents);
        if (model != null) payload.put("model", model);
        if (topN != null) payload.put("top_n", topN);
        payload.put("caller_service", "serving");
        if (knowledgeDomain != null && !knowledgeDomain.isBlank()) {
            payload.put("knowledge_domain", knowledgeDomain);
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

    public void ensureTemplates() {
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
