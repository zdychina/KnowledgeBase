package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.*;
import com.coremasterkb.serving.domainpack.ServingDomainProfile;
import org.springframework.stereotype.Component;

import java.util.*;

/**
 * Intent-aware dynamic route plan generation.
 *
 * <p>Routing uses a two-layer strategy:
 * <ol>
 *   <li><b>Complexity tier</b> determines which retrieval routes are enabled.</li>
 *   <li><b>Intent</b> is used as a tie-breaker when domain profile supplies per-intent overrides.</li>
 * </ol>
 */
@Component
public class RetrievalRouter {

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
                "entity_exact", Map.of("weight", 0.7, "top_k", 20.0),
                "entity_graph", Map.of("weight", 0.6, "top_k", 20.0)
        ));
        COMPLEXITY_ROUTES = Collections.unmodifiableMap(cr);
    }

    private static final Map<String, Map<String, Map<String, Double>>> BUILTIN_ROUTES;

    static {
        Map<String, Map<String, Map<String, Double>>> routes = new LinkedHashMap<>();
        routes.put("default", Map.of(
                "lexical_bm25", Map.of("weight", 1.0, "top_k", 50.0),
                "dense_vector", Map.of("weight", 0.9, "top_k", 50.0),
                "entity_exact", Map.of("weight", 0.8, "top_k", 20.0)
        ));
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
                "entity_exact", Map.of("weight", 0.7, "top_k", 15.0),
                "entity_graph", Map.of("weight", 0.6, "top_k", 20.0)
        ));
        routes.put("comparison", Map.of(
                "lexical_bm25", Map.of("weight", 1.0, "top_k", 50.0),
                "dense_vector", Map.of("weight", 1.0, "top_k", 50.0),
                "entity_graph", Map.of("weight", 0.7, "top_k", 20.0)
        ));
        BUILTIN_ROUTES = Collections.unmodifiableMap(routes);
    }

    private static final Map<String, List<String>> INTENT_EXPANSION = Map.of(
            "troubleshooting", List.of("causes", "results_in", "enables", "conditions", "elaborates", "backgrounds"),
            "comparison",      List.of("contrasts_with", "parallels", "elaborates"),
            "procedure",       List.of("purposes", "enables", "sequences", "conditions", "elaborates")
    );

    private static final Map<String, String> INTENT_RERANK = Map.of(
            "troubleshooting", "cascade",
            "comparison",      "cascade",
            "procedure",       "cascade"
    );

    private static final int INTENT_EXPANSION_MAX_EXPANDED = 8;
    private static final int INTENT_EXPANSION_MAX_DEPTH = 2;

    public RetrievalRoutePlan route(QueryUnderstanding understanding, ServingDomainProfile profile) {
        String intent = understanding.intent();
        String complexity = understanding.queryComplexity();

        Map<String, Map<String, Double>> routeWeights =
                COMPLEXITY_ROUTES.getOrDefault(complexity, COMPLEXITY_ROUTES.get("medium"));

        if (profile != null && profile.routePolicy() != null && !profile.routePolicy().isEmpty()) {
            Map<String, Map<String, Double>> profilePolicy = profile.getRoutePolicyForIntent(intent);
            if (profilePolicy != null && !profilePolicy.isEmpty()) {
                routeWeights = profilePolicy;
            }
        }

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

        Map<String, Object> intentOverride = profile != null
                ? profile.intentStrategyFor(intent) : Map.of();

        String rerankMethod = resolveRerankMethod(intent, complexity, understanding, intentOverride);

        long enabledCount = routeConfigs.stream().filter(RouteConfig::enabled).count();
        String fusionMethod = enabledCount > 1 ? "weighted_rrf" : "identity";

        AssemblyConfig assemblyConfig = resolveAssembly(intent, complexity, intentOverride);

        return new RetrievalRoutePlan(
                routeConfigs,
                understanding.scope(),
                new FusionConfig(fusionMethod, 60),
                new RerankConfig(rerankMethod, "score"),
                assemblyConfig,
                ExpansionConfig.defaults()
        );
    }

    private static String resolveRerankMethod(
            String intent, String complexity, QueryUnderstanding understanding,
            Map<String, Object> intentOverride) {
        if (intentOverride.get("rerank") instanceof String s && !s.isBlank()) {
            return s;
        }
        String builtin = INTENT_RERANK.get(intent);
        if (builtin != null) return builtin;
        if ("complex".equals(complexity)) return "cascade";
        if (understanding.evidenceNeed() != null && understanding.evidenceNeed().needsComparison()) {
            return "cascade";
        }
        return "score";
    }

    @SuppressWarnings("unchecked")
    private static AssemblyConfig resolveAssembly(
            String intent, String complexity, Map<String, Object> intentOverride) {
        // Graph expansion is enabled for all complexity tiers.
        // Previously disabled for non-complex, causing context loss.
        AssemblyConfig base = AssemblyConfig.defaults();

        List<String> builtinTypes = INTENT_EXPANSION.get(intent);
        Map<String, Object> ge = intentOverride.get("graph_expand") instanceof Map<?, ?> m
                ? (Map<String, Object>) m : Map.of();

        if (builtinTypes == null && ge.isEmpty()) return base;

        boolean enabled = ge.get("enabled") instanceof Boolean b ? b : true;
        List<String> relationTypes = ge.get("relation_types") instanceof List<?> l
                ? l.stream().map(String::valueOf).toList()
                : (builtinTypes != null ? builtinTypes : base.relationTypes());
        int maxDepth = ge.get("max_depth") instanceof Number n
                ? n.intValue() : Math.max(base.maxRelationDepth(), INTENT_EXPANSION_MAX_DEPTH);
        int maxExpanded = ge.get("max_expanded") instanceof Number n2
                ? n2.intValue() : Math.max(base.maxExpanded(), INTENT_EXPANSION_MAX_EXPANDED);
        int maxItems = base.maxItems() > 0 ? base.maxItems() : 10;

        return new AssemblyConfig(true, enabled, maxItems, maxExpanded, maxDepth, relationTypes);
    }
}
