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
        this.restTemplate = buildRestTemplate((int) config.getTimeout().toMillis());
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
     *
     * @param payload request body
     * @return task response map (contains task_id etc.), or empty map on any error
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

    private RestTemplate buildRestTemplate(int timeoutMillis) {
        org.springframework.http.client.SimpleClientHttpRequestFactory factory =
                new org.springframework.http.client.SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(timeoutMillis);
        factory.setReadTimeout(timeoutMillis);
        return new RestTemplate(factory);
    }
}
