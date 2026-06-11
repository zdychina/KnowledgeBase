package com.coremasterkb.serving.application;

import com.coremasterkb.serving.infrastructure.LlmClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;

/**
 * Generates semantic query variants for multi-query retrieval expansion.
 *
 * <p>Calls the LLM service with the {@code serving-multi-query-expansion} template
 * to produce 2-3 paraphrases of the original query. Each variant is subsequently
 * used for an independent retrieval call; their candidates are merged before fusion.
 * Falls back to {@code [originalQuery]} when the LLM service is unavailable.</p>
 */
@Component
public class MultiQueryExpander {

    private static final Logger log = LoggerFactory.getLogger(MultiQueryExpander.class);
    private static final int MAX_EXTRA_VARIANTS = 2;

    private final LlmClient llmClient;

    public MultiQueryExpander(LlmClient llmClient) {
        this.llmClient = llmClient;
    }

    /**
     * Expand the query into a list that always starts with the original query,
     * followed by up to {@value MAX_EXTRA_VARIANTS} LLM-generated variants.
     *
     * @param query original user query
     * @return list of queries (original first); at least size 1
     */
    public List<String> expand(String query) {
        if (llmClient == null || !llmClient.isAvailable()) {
            return List.of(query);
        }
        try {
            Map<String, Object> result = llmClient.execute(
                    "multi_query", "serving-multi-query-expansion", Map.of("query", query));

            List<String> variants = extractVariants(result);
            if (variants.isEmpty()) {
                return List.of(query);
            }

            List<String> all = new ArrayList<>();
            all.add(query);
            variants.stream()
                    .filter(v -> v != null && !v.isBlank() && !v.equals(query))
                    .limit(MAX_EXTRA_VARIANTS)
                    .forEach(all::add);
            log.debug("Multi-query expanded '{}' to {} variants", query, all.size());
            return Collections.unmodifiableList(all);
        } catch (Exception e) {
            log.warn("Multi-query expansion failed, using single query: {}", e.getMessage());
            return List.of(query);
        }
    }

    @SuppressWarnings("unchecked")
    private static List<String> extractVariants(Map<String, Object> response) {
        Map<String, Object> unwrapped = LlmClient.unwrapResponse(response);
        Object resultObj = unwrapped.getOrDefault("result", unwrapped);
        if (resultObj instanceof Map<?, ?> inner) {
            Object parsed = inner.get("parsed_output");
            if (parsed instanceof Map<?, ?> parsedMap) {
                Object variantsObj = parsedMap.get("variants");
                if (variantsObj instanceof List<?> list) {
                    return list.stream()
                            .filter(String.class::isInstance)
                            .map(String.class::cast)
                            .toList();
                }
            }
        }
        return List.of();
    }
}
