package com.coremasterkb.serving.infrastructure;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;

public class EmbeddingClient {

    private static final Logger log = LoggerFactory.getLogger(EmbeddingClient.class);

    private final LlmClient llmClient;
    private final String model;
    private final int dimensions;

    public EmbeddingClient(LlmClient llmClient, String model, int dimensions) {
        this.llmClient = llmClient;
        this.model = model;
        this.dimensions = dimensions;
    }

    public boolean isConfigured() {
        return llmClient.isAvailable();
    }

    @SuppressWarnings("unchecked")
    public float[] embed(String text) {
        Map<String, Object> response = llmClient.embed(List.of(text), model, dimensions);
        List<Map<String, Object>> data = (List<Map<String, Object>>) response.get("data");
        if (data != null && !data.isEmpty()) {
            List<Number> embedding = (List<Number>) data.get(0).get("embedding");
            if (embedding != null) {
                float[] result = new float[embedding.size()];
                for (int i = 0; i < embedding.size(); i++) {
                    result[i] = embedding.get(i).floatValue();
                }
                return result;
            }
        }
        return null;
    }

    /**
     * HyDE: generate a hypothetical document via LLM, then embed it.
     * Falls back to plain query embedding on any failure.
     */
    public float[] embedHyDE(String query) {
        try {
            Map<String, Object> result = llmClient.execute(
                    "hyde", "serving-hyde-expansion", Map.of("query", query));

            String hypotheticalDoc = extractRawOutput(result);
            if (hypotheticalDoc != null && !hypotheticalDoc.isBlank()) {
                float[] hydeEmbedding = embed(hypotheticalDoc);
                if (hydeEmbedding != null) {
                    log.debug("HyDE expansion succeeded, hypothetical doc length={}", hypotheticalDoc.length());
                    return hydeEmbedding;
                }
            }
        } catch (Exception e) {
            log.warn("HyDE expansion failed, falling back to direct query embedding: {}", e.getMessage());
        }
        return embed(query);
    }

    @SuppressWarnings("unchecked")
    private static String extractRawOutput(Map<String, Object> response) {
        // Response: {task_id, status, result: {raw_output, parsed_output, ...}}
        Object innerObj = response.getOrDefault("result", response);
        if (innerObj instanceof Map<?, ?> inner) {
            Object rawOutput = inner.get("raw_output");
            if (rawOutput instanceof String s) {
                return s.strip();
            }
        }
        return null;
    }
}
