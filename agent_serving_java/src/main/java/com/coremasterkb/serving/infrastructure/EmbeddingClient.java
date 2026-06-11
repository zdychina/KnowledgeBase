package com.coremasterkb.serving.infrastructure;

import java.util.*;

/**
 * Client for text embedding via llm_service.
 *
 * <p>Model and dimensions are managed by llm_service — this client only sends
 * the text input and relies on llm_service defaults.
 */
public class EmbeddingClient {

    private final LlmClient llmClient;

    public EmbeddingClient(LlmClient llmClient) {
        this.llmClient = llmClient;
    }

    public boolean isConfigured() {
        return llmClient.isAvailable();
    }

    @SuppressWarnings("unchecked")
    public float[] embed(String text) {
        Map<String, Object> response = llmClient.embed(List.of(text));
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
                    return hydeEmbedding;
                }
            }
        } catch (Exception e) {
            // fallback to direct query embedding
        }
        return embed(query);
    }

    @SuppressWarnings("unchecked")
    private static String extractRawOutput(Map<String, Object> response) {
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
