package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.EntityRef;
import com.coremasterkb.serving.domain.NormalizedQuery;
import com.coremasterkb.serving.domain.QueryPlan;

import java.util.List;
import java.util.Map;

/**
 * Facade that delegates to the configured PlannerProvider.
 */
public class QueryPlanner {

    private final PlannerProvider provider;

    public QueryPlanner(PlannerProvider provider) {
        this.provider = provider;
    }

    /**
     * Build a QueryPlan from a normalized query, with optional request-level overrides.
     */
    public QueryPlan plan(
            NormalizedQuery normalized,
            Map<String, Object> scopeOverride,
            List<EntityRef> entitiesOverride
    ) {
        return provider.buildPlan(normalized, scopeOverride, entitiesOverride);
    }
}
