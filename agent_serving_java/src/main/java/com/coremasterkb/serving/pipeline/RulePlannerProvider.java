package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.*;

import java.util.*;

/**
 * Deterministic rule-based planner.
 * Translated from the Python pipeline plan() logic.
 *
 * Passes keywords, intent, entities, and scope from NormalizedQuery;
 * applies overrides where provided; uses default budget and expansion configs.
 */
public class RulePlannerProvider implements PlannerProvider {

    @Override
    public QueryPlan buildPlan(
            NormalizedQuery normalized,
            Map<String, Object> scopeOverride,
            List<EntityRef> entitiesOverride
    ) {
        String intent = normalized.intent();

        // Effective entities: prefer override if supplied and non-empty
        List<EntityRef> entities;
        if (entitiesOverride != null && !entitiesOverride.isEmpty()) {
            entities = entitiesOverride;
        } else {
            entities = normalized.entities() != null ? normalized.entities() : Collections.emptyList();
        }

        // Effective scope: prefer override if supplied and non-empty
        Map<String, Object> scope;
        if (scopeOverride != null && !scopeOverride.isEmpty()) {
            scope = scopeOverride;
        } else {
            scope = normalized.scope() != null ? normalized.scope() : Collections.emptyMap();
        }

        List<String> keywords = normalized.keywords() != null
                ? normalized.keywords() : Collections.emptyList();
        List<String> desiredRoles = normalized.desiredRoles() != null
                ? normalized.desiredRoles() : Collections.emptyList();

        return new QueryPlan(
                intent,
                keywords,
                entities,
                scope,
                desiredRoles,
                Collections.emptyList(), // desiredBlockTypes — rule planner does not set these
                new RetrievalBudget(),
                new ExpansionConfig(),
                new RetrieverConfig(),
                new RerankerConfig()
        );
    }
}
