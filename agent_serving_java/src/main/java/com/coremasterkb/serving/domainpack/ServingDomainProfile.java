package com.coremasterkb.serving.domainpack;

import java.util.*;

public record ServingDomainProfile(
    String domainId,
    Set<String> entityTypes,
    Set<String> strongEntityTypes,
    Map<String, Map<String, Map<String, Double>>> routePolicy,
    List<Map<String, Object>> extractorRules,
    List<Map<String, Object>> evalQuestions,
    Map<String, Object> queryUnderstanding
) {
    public ServingDomainProfile {
        if (entityTypes == null) entityTypes = Set.of();
        if (strongEntityTypes == null) strongEntityTypes = Set.of();
        if (routePolicy == null) routePolicy = Map.of();
        if (extractorRules == null) extractorRules = List.of();
        if (evalQuestions == null) evalQuestions = List.of();
        if (queryUnderstanding == null) queryUnderstanding = Map.of();
    }

    public Map<String, Map<String, Double>> getRoutePolicyForIntent(String intent) {
        return routePolicy.getOrDefault(intent, routePolicy.getOrDefault("default", Map.of()));
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
            domainId, Set.of(), Set.of(), Collections.unmodifiableMap(fullPolicy),
            List.of(), List.of(), Map.of()
        );
    }
}
