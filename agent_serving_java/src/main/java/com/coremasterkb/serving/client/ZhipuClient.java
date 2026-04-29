package com.coremasterkb.serving.client;

import com.coremasterkb.serving.config.ServingProperties;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.*;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

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

    /** True when an API key is configured. */
    public boolean isConfigured() {
        return config.isConfigured();
    }

    /**
     * Embed a single text string.
     *
     * @return float array of length {@code config.embeddingDimensions},
     *         or empty array on any error / not configured
     */
    @SuppressWarnings("unchecked")
    public float[] embed(String text) {
        if (!config.isConfigured()) return new float[0];
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
        if (!config.isConfigured() || texts == null || texts.isEmpty()) {
            return Collections.emptyList();
        }
        return texts.stream()
                .map(this::embed)
                .toList();
    }
}
