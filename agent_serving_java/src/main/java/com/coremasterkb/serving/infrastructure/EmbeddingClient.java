package com.coremasterkb.serving.infrastructure;

import java.util.*;

public class EmbeddingClient {

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
}
