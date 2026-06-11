package com.coremasterkb.serving.domainpack;

import java.util.*;

/**
 * Per-domain serving config consumed at query time. Built from the scenario pack's
 * {@code serving:} block. Only fields Serving actually reads are kept — ontology
 * ({@code entity_types}/{@code strong_entity_types}) and {@code eval_questions} are
 * deliberately excluded (Mining/eval concerns, never read here).
 */
public record ServingDomainProfile(
    String domainId,
    Map<String, Map<String, Map<String, Double>>> routePolicy,
    List<Map<String, Object>> extractorRules,
    Map<String, Object> queryUnderstanding,
    Map<String, Object> intentStrategy
) {
    public ServingDomainProfile {
        if (routePolicy == null) routePolicy = Map.of();
        if (extractorRules == null) extractorRules = List.of();
        if (queryUnderstanding == null) queryUnderstanding = Map.of();
        if (intentStrategy == null) intentStrategy = Map.of();
    }

    public Map<String, Map<String, Double>> getRoutePolicyForIntent(String intent) {
        return routePolicy.getOrDefault(intent, routePolicy.getOrDefault("default", Map.of()));
    }

    /**
     * Per-intent strategy overrides (graph_expand / rerank) from
     * {@code serving.intent_strategy.<intent>}. Empty when unset.
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> intentStrategyFor(String intent) {
        Object v = intentStrategy.get(intent);
        return v instanceof Map<?, ?> m ? (Map<String, Object>) m : Map.of();
    }

    /**
     * Build a default ServingDomainProfile with route policy matching Python's _DEFAULT_ROUTE_POLICY.
     */
    public static ServingDomainProfile defaults(String domainId) {
        Map<String, Map<String, Double>> defaultPolicy = Map.of(
            "lexical_bm25", Map.of("weight", 1.0, "top_k", 50.0),
            "entity_exact", Map.of("weight", 1.0, "top_k", 30.0),
            "dense_vector", Map.of("weight", 0.8, "top_k", 50.0)
        );

        Map<String, Map<String, Map<String, Double>>> fullPolicy = new LinkedHashMap<>();
        fullPolicy.put("default", defaultPolicy);
        fullPolicy.put("command_usage", Map.of(
            "entity_exact", Map.of("weight", 1.4, "top_k", 20.0),
            "lexical_bm25", Map.of("weight", 1.0, "top_k", 50.0),
            "dense_vector", Map.of("weight", 0.5, "top_k", 30.0)
        ));
        fullPolicy.put("concept_lookup", Map.of(
            "dense_vector", Map.of("weight", 1.2, "top_k", 50.0),
            "lexical_bm25", Map.of("weight", 1.0, "top_k", 50.0),
            "entity_exact", Map.of("weight", 0.6, "top_k", 20.0)
        ));
        fullPolicy.put("troubleshooting", Map.of(
            "lexical_bm25", Map.of("weight", 1.0, "top_k", 50.0),
            "entity_exact", Map.of("weight", 1.2, "top_k", 30.0),
            "dense_vector", Map.of("weight", 0.6, "top_k", 30.0)
        ));
        fullPolicy.put("comparison", Map.of(
            "lexical_bm25", Map.of("weight", 1.0, "top_k", 50.0),
            "dense_vector", Map.of("weight", 1.0, "top_k", 50.0),
            "entity_exact", Map.of("weight", 1.0, "top_k", 30.0)
        ));
        fullPolicy.put("general", defaultPolicy);

        return new ServingDomainProfile(
            domainId, Collections.unmodifiableMap(fullPolicy),
            List.of(), Map.of(), Map.of()
        );
    }
}
