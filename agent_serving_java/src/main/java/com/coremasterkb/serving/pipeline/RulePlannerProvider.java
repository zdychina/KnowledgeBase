package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.*;

import java.util.*;

/**
 * Deterministic rule-based planner with retrieval routing.
 *
 * Routing logic:
 *   - fts_bm25 (weight=1.0)  : always enabled
 *   - entity_exact (weight=1.0): enabled when entities are present in the query
 *   - dense_vector (weight=0.8): always requested; the retriever falls back silently
 *                                if LLM service is unavailable
 *
 * fusion_method:
 *   - "weighted_rrf" when ≥2 retrievers are enabled
 *   - "identity" when only fts_bm25 is enabled
 */
public class RulePlannerProvider implements PlannerProvider {

    private final int rrfK;
    private final Map<String, Double> retrieverWeights;

    public RulePlannerProvider(int rrfK, Map<String, Double> retrieverWeights) {
        this.rrfK             = rrfK;
        this.retrieverWeights = retrieverWeights;
    }

    @Override
    public QueryPlan buildPlan(
            NormalizedQuery normalized,
            Map<String, Object> scopeOverride,
            List<EntityRef> entitiesOverride
    ) {
        String intent = normalized.intent();

        List<EntityRef> entities = (entitiesOverride != null && !entitiesOverride.isEmpty())
                ? entitiesOverride
                : (normalized.entities() != null ? normalized.entities() : Collections.emptyList());

        Map<String, Object> scope = (scopeOverride != null && !scopeOverride.isEmpty())
                ? scopeOverride
                : (normalized.scope() != null ? normalized.scope() : Collections.emptyMap());

        List<String> keywords    = normalized.keywords()    != null ? normalized.keywords()    : Collections.emptyList();
        List<String> desiredRoles = normalized.desiredRoles() != null ? normalized.desiredRoles() : Collections.emptyList();

        // ---- Retrieval routing ----
        List<String> enabledRetrievers = new ArrayList<>();
        Map<String, Double> weights    = new LinkedHashMap<>();

        enabledRetrievers.add("fts_bm25");
        weights.put("fts_bm25", retrieverWeights.getOrDefault("fts_bm25", 1.0));

        if (!entities.isEmpty()) {
            enabledRetrievers.add("entity_exact");
            weights.put("entity_exact", retrieverWeights.getOrDefault("entity_exact", 1.0));
        }

        // dense_vector is always requested; DenseVectorRetriever handles unavailability
        enabledRetrievers.add("dense_vector");
        weights.put("dense_vector", retrieverWeights.getOrDefault("dense_vector", 0.8));

        String fusionMethod = enabledRetrievers.size() > 1 ? "weighted_rrf" : "identity";

        RetrieverConfig retrieverConfig = new RetrieverConfig(
                Collections.unmodifiableList(enabledRetrievers),
                fusionMethod,
                rrfK,
                Collections.unmodifiableMap(weights)
        );

        return new QueryPlan(
                intent,
                keywords,
                entities,
                scope,
                desiredRoles,
                Collections.emptyList(),
                new RetrievalBudget(),
                new ExpansionConfig(),
                retrieverConfig,
                new RerankerConfig()
        );
    }
}
