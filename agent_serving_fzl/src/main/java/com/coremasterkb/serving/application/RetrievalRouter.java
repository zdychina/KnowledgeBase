package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.*;
import com.coremasterkb.serving.domainpack.ServingDomainProfile;
import org.springframework.stereotype.Component;

import java.util.*;

/**
 * Intent-aware dynamic route plan generation.
 *
 * <p>Reads route policy from the domain profile and builds a
 * {@link RetrievalRoutePlan} with per-route weights and top_k values.
 * Falls back to built-in defaults when no domain pack is available.
 * Matches Python's RetrievalRouter behavior.
 */
@Component
public class RetrievalRouter {

    // Built-in route policy matching Python's _BUILTIN_ROUTES
    private static final Map<String, Map<String, Map<String, Double>>> BUILTIN_ROUTES;

    static {
        Map<String, Map<String, Map<String, Double>>> routes = new LinkedHashMap<>();

        routes.put("default", Map.of(
                "lexical_bm25", Map.of("weight", 1.0, "top_k", 50.0),
                "dense_vector", Map.of("weight", 0.9, "top_k", 50.0)
        ));

        routes.put("command_usage", Map.of(
                "lexical_bm25", Map.of("weight", 1.2, "top_k", 50.0),
                "dense_vector", Map.of("weight", 0.6, "top_k", 30.0)
        ));

        routes.put("concept_lookup", Map.of(
                "dense_vector", Map.of("weight", 1.1, "top_k", 50.0),
                "lexical_bm25", Map.of("weight", 0.8, "top_k", 50.0)
        ));

        routes.put("troubleshooting", Map.of(
                "lexical_bm25", Map.of("weight", 1.0, "top_k", 50.0),
                "dense_vector", Map.of("weight", 0.8, "top_k", 40.0)
        ));

        routes.put("comparison", Map.of(
                "lexical_bm25", Map.of("weight", 1.0, "top_k", 50.0),
                "dense_vector", Map.of("weight", 1.0, "top_k", 50.0)
        ));

        BUILTIN_ROUTES = Collections.unmodifiableMap(routes);
    }

    /**
     * Build a route plan from query understanding.
     *
     * @param understanding query understanding result
     * @param profile       domain profile with optional route policy overrides; may be null
     * @return complete retrieval route plan
     */
    public RetrievalRoutePlan route(QueryUnderstanding understanding, ServingDomainProfile profile) {
        String intent = understanding.intent();

        // Get route weights from domain profile or built-in defaults
        Map<String, Map<String, Double>> routeWeights;
        if (profile != null && profile.routePolicy() != null && !profile.routePolicy().isEmpty()) {
            Map<String, Map<String, Double>> policyForIntent = profile.getRoutePolicyForIntent(intent);
            if (policyForIntent != null && !policyForIntent.isEmpty()) {
                routeWeights = policyForIntent;
            } else {
                routeWeights = BUILTIN_ROUTES.getOrDefault(intent, BUILTIN_ROUTES.get("default"));
            }
        } else {
            routeWeights = BUILTIN_ROUTES.getOrDefault(intent, BUILTIN_ROUTES.get("default"));
        }

        // Build route configs
        List<RouteConfig> routeConfigs = new ArrayList<>();
        for (var entry : routeWeights.entrySet()) {
            String routeName = entry.getKey();
            Map<String, Double> config = entry.getValue();
            routeConfigs.add(new RouteConfig(
                    routeName,
                    true,
                    config.getOrDefault("weight", 1.0),
                    config.getOrDefault("top_k", 50.0).intValue()
            ));
        }

        // Determine rerank strategy
        String rerankMethod = "score";
        if (understanding.evidenceNeed() != null && understanding.evidenceNeed().needsComparison()) {
            rerankMethod = "cascade";
        }

        // Determine fusion method based on number of enabled routes
        long enabledCount = routeConfigs.stream().filter(RouteConfig::enabled).count();
        String fusionMethod = enabledCount > 1 ? "weighted_rrf" : "identity";

        return new RetrievalRoutePlan(
                routeConfigs,
                understanding.scope(),
                new FusionConfig(fusionMethod, 60),
                new RerankConfig(rerankMethod, "score"),
                AssemblyConfig.defaults(),
                ExpansionConfig.defaults()
        );
    }
}
