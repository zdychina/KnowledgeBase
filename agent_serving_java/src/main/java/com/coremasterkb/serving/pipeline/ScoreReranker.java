package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.EntityRef;
import com.coremasterkb.serving.domain.QueryPlan;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.util.JsonUtils;

import java.util.*;

/**
 * Score-based reranker with 4 stages.
 * Translated from pipeline/reranker.py (ScoreReranker).
 *
 * Stage 1: Deduplicate raw_text/contextual_text units by source_segment_id (keep highest score).
 * Stage 2: Downweight low-value block types (heading, toc, link) by 0.3x.
 * Stage 3: Rule-based score boosts.
 * Stage 4: Sort descending, truncate to budget.maxItems.
 */
public class ScoreReranker implements Reranker {

    private static final Set<String> LOW_VALUE_BLOCK_TYPES = Set.of("heading", "toc", "link");

    private final double lowValueBlockPenalty;
    private final double boostSemanticRole;
    private final double boostBlockType;
    private final double boostScopeMatch;
    private final double boostEntityMatch;

    public ScoreReranker(double lowValueBlockPenalty, double boostSemanticRole,
                         double boostBlockType, double boostScopeMatch, double boostEntityMatch) {
        this.lowValueBlockPenalty = lowValueBlockPenalty;
        this.boostSemanticRole    = boostSemanticRole;
        this.boostBlockType       = boostBlockType;
        this.boostScopeMatch      = boostScopeMatch;
        this.boostEntityMatch     = boostEntityMatch;
    }

    @Override
    public List<RetrievalCandidate> rerank(List<RetrievalCandidate> candidates, QueryPlan plan) {
        if (candidates == null || candidates.isEmpty()) {
            return Collections.emptyList();
        }

        // Stage 1: Deduplicate by source_segment_id
        List<RetrievalCandidate> deduped = deduplicateBySourceSegment(candidates);

        // Stage 2 + 3: Compute adjusted scores
        List<RetrievalCandidate> scored = new ArrayList<>();
        for (RetrievalCandidate c : deduped) {
            double score = c.score();

            String blockType = getStringMeta(c, "block_type");
            String unitType  = getStringMeta(c, "unit_type");

            // Stage 2: downweight low-value block types
            if (blockType != null && LOW_VALUE_BLOCK_TYPES.contains(blockType.toLowerCase())) {
                score *= lowValueBlockPenalty;
            }

            // Stage 3: rule-based boosts
            score = applyBoosts(score, c, plan, blockType, unitType);

            scored.add(c.withScore(score));
        }

        // Stage 4: sort desc, truncate
        scored.sort(Comparator.comparingDouble(RetrievalCandidate::score).reversed());
        int maxItems = plan.budget().maxItems();
        if (scored.size() > maxItems) {
            scored = scored.subList(0, maxItems);
        }
        return Collections.unmodifiableList(scored);
    }

    // -------------------------------------------------------------------------
    // Stage 1
    // -------------------------------------------------------------------------

    private List<RetrievalCandidate> deduplicateBySourceSegment(List<RetrievalCandidate> candidates) {
        // For units whose unit_type is raw_text or contextual_text,
        // dedup by source_segment_id keeping highest score.
        Map<String, RetrievalCandidate> bySourceSegment = new LinkedHashMap<>();
        List<RetrievalCandidate> others = new ArrayList<>();

        for (RetrievalCandidate c : candidates) {
            String unitType = getStringMeta(c, "unit_type");
            String sourceSegmentId = getStringMeta(c, "source_segment_id");

            boolean deduplicable = sourceSegmentId != null && !sourceSegmentId.isBlank()
                    && (unitType == null
                        || unitType.equals("raw_text")
                        || unitType.equals("contextual_text"));

            if (deduplicable) {
                bySourceSegment.merge(sourceSegmentId, c, (existing, incoming) ->
                        incoming.score() > existing.score() ? incoming : existing);
            } else {
                others.add(c);
            }
        }

        List<RetrievalCandidate> result = new ArrayList<>(bySourceSegment.values());
        result.addAll(others);
        return result;
    }

    // -------------------------------------------------------------------------
    // Stage 3
    // -------------------------------------------------------------------------

    private double applyBoosts(double score, RetrievalCandidate c, QueryPlan plan,
                                String blockType, String unitType) {
        List<String> desiredRoles       = plan.desiredRoles();
        List<String> desiredBlockTypes  = plan.desiredBlockTypes();
        Map<String, Object> scopeConstraints = plan.scopeConstraints();
        List<EntityRef> entityConstraints    = plan.entityConstraints();

        // Boost: semantic_role in desired_roles
        String semanticRole = getStringMeta(c, "semantic_role");
        if (semanticRole != null && desiredRoles != null && desiredRoles.contains(semanticRole)) {
            score += boostSemanticRole;
        }

        // Boost: block_type in desired_block_types
        if (blockType != null && desiredBlockTypes != null && desiredBlockTypes.contains(blockType)) {
            score += boostBlockType;
        }

        // Boost: scope match in facets_json
        String facetsJson = getStringMeta(c, "facets_json");
        if (facetsJson != null && !facetsJson.isBlank() && !scopeConstraints.isEmpty()) {
            Map<String, Object> facets = JsonUtils.safeJsonParse(facetsJson);
            if (scopeMatchesFacets(scopeConstraints, facets)) {
                score += boostScopeMatch;
            }
        }

        // Boost: entity match in entity_refs_json
        String entityRefsJson = getStringMeta(c, "entity_refs_json");
        if (entityRefsJson != null && !entityRefsJson.isBlank()
                && entityConstraints != null && !entityConstraints.isEmpty()) {
            if (entityMatchesRefs(entityConstraints, entityRefsJson)) {
                score += boostEntityMatch;
            }
        }

        return score;
    }

    private boolean scopeMatchesFacets(Map<String, Object> scope, Map<String, Object> facets) {
        for (Map.Entry<String, Object> entry : scope.entrySet()) {
            Object facetValue = facets.get(entry.getKey());
            if (facetValue != null && facetValue.equals(entry.getValue())) {
                return true;
            }
        }
        return false;
    }

    @SuppressWarnings("unchecked")
    private boolean entityMatchesRefs(List<EntityRef> constraints, String entityRefsJson) {
        try {
            Object parsed = JsonUtils.mapper().readValue(entityRefsJson, Object.class);
            List<Map<String, Object>> refs = new ArrayList<>();
            if (parsed instanceof List<?> list) {
                for (Object item : list) {
                    if (item instanceof Map<?, ?> m) {
                        refs.add((Map<String, Object>) m);
                    }
                }
            }
            for (EntityRef constraint : constraints) {
                String cName = constraint.normalizedName().isBlank()
                        ? constraint.name() : constraint.normalizedName();
                for (Map<String, Object> ref : refs) {
                    Object refName = ref.get("normalized_name");
                    if (refName == null) refName = ref.get("name");
                    if (cName.equalsIgnoreCase(String.valueOf(refName))) {
                        return true;
                    }
                }
            }
        } catch (Exception ignored) {
        }
        return false;
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    private String getStringMeta(RetrievalCandidate c, String key) {
        Object val = c.metadata().get(key);
        return val instanceof String s ? s : null;
    }
}
