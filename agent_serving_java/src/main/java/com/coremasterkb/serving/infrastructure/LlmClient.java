package com.coremasterkb.serving.infrastructure;

import org.springframework.http.*;
import org.springframework.web.client.RestTemplate;

import java.util.*;

public class LlmClient {

    private final RestTemplate restTemplate;
    private final String baseUrl;
    private final String apiKey;

    public LlmClient(RestTemplate restTemplate, String baseUrl, String apiKey) {
        this.restTemplate = restTemplate;
        this.baseUrl = baseUrl;
        this.apiKey = apiKey;
    }

    public boolean isAvailable() {
        return baseUrl != null && !baseUrl.isBlank()
                && apiKey != null && !apiKey.isBlank();
    }

    public Map<String, Object> execute(String pipelineStage, String templateKey, Map<String, Object> input) {
        if (!isAvailable()) {
            throw new IllegalStateException("LLM client not configured");
        }

        Map<String, Object> payload = new HashMap<>();
        payload.put("pipeline_stage", pipelineStage);
        payload.put("template_key", templateKey);
        payload.put("input", input);

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        if (apiKey != null && !apiKey.isBlank()) {
            headers.setBearerAuth(apiKey);
        }

        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(payload, headers);
        ResponseEntity<Map> response = restTemplate.postForEntity(baseUrl, entity, Map.class);
        return response.getBody() != null ? response.getBody() : Map.of();
    }

    public Map<String, Object> embed(List<String> texts, String model, Integer dimensions) {
        if (!isAvailable()) {
            throw new IllegalStateException("LLM client not configured");
        }

        Map<String, Object> payload = new HashMap<>();
        payload.put("input", texts);
        if (model != null) payload.put("model", model);
        if (dimensions != null) payload.put("dimensions", dimensions);

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        if (apiKey != null && !apiKey.isBlank()) {
            headers.setBearerAuth(apiKey);
        }

        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(payload, headers);
        ResponseEntity<Map> response = restTemplate.postForEntity(baseUrl + "/embeddings", entity, Map.class);
        return response.getBody() != null ? response.getBody() : Map.of();
    }
}
