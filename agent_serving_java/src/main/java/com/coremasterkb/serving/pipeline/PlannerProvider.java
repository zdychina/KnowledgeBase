package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.EntityRef;
import com.coremasterkb.serving.domain.NormalizedQuery;
import com.coremasterkb.serving.domain.QueryPlan;

import java.util.List;
import java.util.Map;

/**
 * PlannerProvider SPI — converts a normalized query into a QueryPlan.
 */
public interface PlannerProvider {

    /**
     * Build a query plan from the normalized query plus optional overrides.
     *
     * @param normalized       normalized query from QueryNormalizer
     * @param scopeOverride    optional scope override from the original request
     * @param entitiesOverride optional entities override from the original request
     * @return a fully populated QueryPlan
     */
    QueryPlan buildPlan(
            NormalizedQuery normalized,
            Map<String, Object> scopeOverride,
            List<EntityRef> entitiesOverride
    );
}
