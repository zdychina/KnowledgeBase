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

    /**
     * Complexity-driven base routes.
     * simple  → entity_exact + BM25 only (entity precision match)
     * medium  → BM25 + Dense Vector (semantic retrieval)
     * complex → all three routes (full retrieval + graph expansion)
     */
    private static final Map<String, Map<String, Map<String, Double>>> COMPLEXITY_ROUTES;

    static {
        Map<String, Map<String, Map<String, Double>>> cr = new LinkedHashMap<>();
        cr.put("simple", Map.of(
                "entity_exact", Map.of("weight", 1.5, "top_k", 20.0),
                "lexical_bm25", Map.of("weight", 1.0, "top_k", 50.0)
        ));
        cr.put("medium", Map.of(
                "lexical_bm25", Map.of("weight", 1.0, "top_k", 50.0),
                "dense_vector", Map.of("weight", 0.9, "top_k", 50.0)
        ));
        cr.put("complex", Map.of(
                "lexical_bm25", Map.of("weight", 1.0, "top_k", 50.0),
                "dense_vector", Map.of("weight", 0.9, "top_k", 50.0),
                "entity_exact", Map.of("weight", 0.7, "top_k", 20.0)
        ));
        COMPLEXITY_ROUTES = Collections.unmodifiableMap(cr);
    }

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
     * <p>Routing uses a two-layer strategy:
     * <ol>
     *   <li><b>Complexity tier</b> ({@code queryComplexity}) determines which retrieval routes are
     *       enabled and whether graph expansion is on.  This is the primary selector.</li>
     *   <li><b>Intent</b> is used as a tie-breaker when the domain profile supplies an explicit
     *       per-intent policy that overrides the complexity defaults.</li>
     * </ol>
     *
     * @param understanding query understanding result (includes {@code queryComplexity})
     * @param profile       domain profile with optional route policy overrides; may be null
     * @return complete retrieval route plan
     */
    public RetrievalRoutePlan route(QueryUnderstanding understanding, ServingDomainProfile profile) {
        String intent = understanding.intent();
        String complexity = understanding.queryComplexity(); // "simple" | "medium" | "complex"

        // Complexity-driven base routes (primary selector)
        Map<String, Map<String, Double>> routeWeights =
                COMPLEXITY_ROUTES.getOrDefault(complexity, COMPLEXITY_ROUTES.get("medium"));

        // Domain profile may override the route weights for the resolved intent
        if (profile != null && profile.routePolicy() != null && !profile.routePolicy().isEmpty()) {
            Map<String, Map<String, Double>> profilePolicy = profile.getRoutePolicyForIntent(intent);
            if (profilePolicy != null && !profilePolicy.isEmpty()) {
                routeWeights = profilePolicy;
            }
        }

        // Build route configs
        List<RouteConfig> routeConfigs = new ArrayList<>();
        for (var entry : routeWeights.entrySet()) {
            Map<String, Double> cfg = entry.getValue();
            routeConfigs.add(new RouteConfig(
                    entry.getKey(),
                    true,
                    cfg.getOrDefault("weight", 1.0),
                    cfg.getOrDefault("top_k", 50.0).intValue()
            ));
        }

        // Rerank: complex always uses cascade; others use cascade only if comparison is needed
        String rerankMethod = "complex".equals(complexity) ? "cascade"
                : (understanding.evidenceNeed() != null && understanding.evidenceNeed().needsComparison()
                        ? "cascade" : "score");

        // Fusion: weighted_rrf when more than one route is active
        long enabledCount = routeConfigs.stream().filter(RouteConfig::enabled).count();
        String fusionMethod = enabledCount > 1 ? "weighted_rrf" : "identity";

        // Graph expansion: only for complex queries (simple/medium skip expansion to save latency)
        AssemblyConfig assemblyConfig = "complex".equals(complexity)
                ? AssemblyConfig.defaults()
                : new AssemblyConfig(true, false, 10, 0, 0, List.of());

        return new RetrievalRoutePlan(
                routeConfigs,
                understanding.scope(),
                new FusionConfig(fusionMethod, 60),
                new RerankConfig(rerankMethod, "score"),
                assemblyConfig,
                ExpansionConfig.defaults()
        );
    }
}
