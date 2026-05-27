package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.*;
import com.coremasterkb.serving.domainpack.ServingDomainProfile;
import org.springframework.stereotype.Component;

import java.util.*;
import java.util.Set;

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

        // entity_exact weight=0.8 gives it a voice in the fusion without dominating
        routes.put("default", Map.of(
                "lexical_bm25", Map.of("weight", 1.0, "top_k", 50.0),
                "dense_vector", Map.of("weight", 0.9, "top_k", 50.0),
                "entity_exact", Map.of("weight", 0.8, "top_k", 20.0)
        ));

        // command_usage: entity_exact is the highest-confidence route — commands are exact-match
        routes.put("command_usage", Map.of(
                "entity_exact", Map.of("weight", 1.5, "top_k", 20.0),
                "lexical_bm25", Map.of("weight", 1.2, "top_k", 50.0),
                "dense_vector", Map.of("weight", 0.6, "top_k", 30.0)
        ));

        routes.put("concept_lookup", Map.of(
                "dense_vector", Map.of("weight", 1.1, "top_k", 50.0),
                "lexical_bm25", Map.of("weight", 0.8, "top_k", 50.0)
        ));

        routes.put("troubleshooting", Map.of(
                "lexical_bm25", Map.of("weight", 1.0, "top_k", 50.0),
                "dense_vector", Map.of("weight", 0.8, "top_k", 40.0),
                "entity_exact", Map.of("weight", 0.7, "top_k", 15.0)
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

        // Adaptive routing: adjust routes based on query complexity
        String complexity = computeComplexity(understanding);
        routeConfigs = applyComplexity(routeConfigs, complexity);

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

    // =========================================================================
    // Adaptive routing helpers
    // =========================================================================

    /**
     * Classify query complexity.
     * <ul>
     *   <li>simple  — entity present, no sub-queries, exact-match intent</li>
     *   <li>complex — comparison intent or has sub-queries (multi-hop reasoning)</li>
     *   <li>medium  — everything else</li>
     * </ul>
     */
    static String computeComplexity(QueryUnderstanding u) {
        if (!u.subQueries().isEmpty() || "comparison".equals(u.intent())) {
            return "complex";
        }
        if (Set.of("command_usage", "concept_lookup", "navigational").contains(u.intent())
                && !u.entities().isEmpty()) {
            return "simple";
        }
        return "medium";
    }

    /**
     * Apply complexity rules to the candidate route list:
     * <ul>
     *   <li>simple  — disable dense_vector (exact lexical + entity match is sufficient)</li>
     *   <li>complex — increase topK by 50% for broader recall</li>
     *   <li>medium  — no change</li>
     * </ul>
     */
    private static List<RouteConfig> applyComplexity(List<RouteConfig> routes, String complexity) {
        return switch (complexity) {
            case "simple" -> routes.stream()
                    .map(r -> "dense_vector".equals(r.name())
                            ? new RouteConfig(r.name(), false, r.weight(), r.topK())
                            : r)
                    .toList();
            case "complex" -> routes.stream()
                    .map(r -> new RouteConfig(r.name(), r.enabled(), r.weight(), (int) (r.topK() * 1.5)))
                    .toList();
            default -> routes;
        };
    }
}
