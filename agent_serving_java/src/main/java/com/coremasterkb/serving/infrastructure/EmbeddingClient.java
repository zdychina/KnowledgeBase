package com.coremasterkb.serving.infrastructure;

import java.util.*;

/**
 * Client for text embedding via llm_service.
 *
 * <p>Model and dimensions are managed by llm_service — this client only sends
 * the text input and relies on llm_service defaults.
 */
public class EmbeddingClient {

    private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(EmbeddingClient.class);
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
                log.info("[HyDE] generated hypothetical doc ({} chars), embedding...", hypotheticalDoc.length());
                float[] hydeEmbedding = embed(hypotheticalDoc);
                if (hydeEmbedding != null) {
                    return hydeEmbedding;
                }
                log.warn("[HyDE] embedding of hypothetical doc returned null, falling back to query");
            } else {
                log.warn("[HyDE] extractRawOutput returned blank, response keys: {}",
                        result != null ? result.keySet() : "null");
            }
        } catch (Exception e) {
            log.warn("[HyDE] failed, falling back to direct embed: {}", e.getMessage());
        }
        return embed(query);
    }

    @SuppressWarnings("unchecked")
    private static String extractRawOutput(Map<String, Object> response) {
        Map<String, Object> unwrapped = LlmClient.unwrapResponse(response);

        // Format 1: {result: {raw_output: "..."}} (internal task format)
        Object resultObj = unwrapped.getOrDefault("result", unwrapped);
        if (resultObj instanceof Map<?, ?> inner) {
            Object rawOutput = inner.get("raw_output");
            if (rawOutput instanceof String s && !s.isBlank()) {
                return s.strip();
            }
        }

        // Format 2: OpenAI chat completion format {choices: [{message: {content: "..."}}]}
        Object choicesObj = unwrapped.get("choices");
        if (choicesObj instanceof List<?> choices && !choices.isEmpty()) {
            Object first = choices.get(0);
            if (first instanceof Map<?, ?> choice) {
                Object msgObj = choice.get("message");
                if (msgObj instanceof Map<?, ?> msg) {
                    Object content = msg.get("content");
                    if (content instanceof String s && !s.isBlank()) {
                        return s.strip();
                    }
                }
            }
        }

        return null;
    }
}
