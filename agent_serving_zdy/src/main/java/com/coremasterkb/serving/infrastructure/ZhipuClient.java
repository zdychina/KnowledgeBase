package com.coremasterkb.serving.infrastructure;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.*;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

import java.util.*;

/**
 * Client for Zhipu AI API (https://open.bigmodel.cn/api/paas/v4).
 *
 * <p>Supports:
 * <ul>
 *   <li>Rerank: POST /rerank — returns ranked results with relevance scores</li>
 * </ul>
 */
public class ZhipuClient {

    private static final Logger log = LoggerFactory.getLogger(ZhipuClient.class);

    private static final int CONNECT_TIMEOUT_MS = 5_000;
    private static final int READ_TIMEOUT_MS = 30_000;

    private final String apiKey;
    private final String baseUrl;
    private final String rerankModel;
    private final RestTemplate restTemplate;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public ZhipuClient(String apiKey, String baseUrl, String rerankModel) {
        this.apiKey = apiKey != null ? apiKey : "";
        this.baseUrl = baseUrl != null ? baseUrl : "";
        this.rerankModel = rerankModel != null ? rerankModel : "";
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(CONNECT_TIMEOUT_MS);
        factory.setReadTimeout(READ_TIMEOUT_MS);
        this.restTemplate = new RestTemplate(factory);
    }

    public boolean isAvailable() {
        return apiKey != null && !apiKey.isBlank()
                && baseUrl != null && !baseUrl.isBlank();
    }

    /**
     * Rerank documents against a query.
     *
     * <p>Endpoint: POST /rerank
     * Request:  {"model": "...", "query": "...", "documents": [...], "top_n": N}
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
            body.put("model", rerankModel);
            body.put("query", query);
            body.put("documents", documents);
            body.put("top_n", topN);

            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            headers.set("Authorization", "Bearer " + apiKey);

            String requestBody = objectMapper.writeValueAsString(body);
            HttpEntity<String> entity = new HttpEntity<>(requestBody, headers);

            String url = baseUrl + "/rerank";
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

            List<Map<String, Object>> out = new ArrayList<>();
            for (Object item : rawList) {
                if (!(item instanceof Map<?, ?> m)) continue;
                Map<String, Object> r = (Map<String, Object>) m;
                Object idxObj = r.get("index");
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
