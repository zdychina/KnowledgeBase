package com.coremasterkb.serving.domain;

import java.util.List;
import java.util.Map;

/**
 * Result of query understanding / analysis phase.
 *
 * @param originalQuery  the raw user query
 * @param intent         inferred intent; defaults to "general"
 * @param subQueries     decomposed sub-queries; defaults to empty list
 * @param entities       recognized entities; defaults to empty list
 * @param scope          scope constraints; defaults to empty map
 * @param keywords       extracted keywords; defaults to empty list
 * @param evidenceNeed   describes evidence requirements; defaults to empty()
 * @param ambiguities    detected ambiguities; defaults to empty list
 * @param source         origin of the understanding (e.g. "rule", "llm"); defaults to "rule"
 */
public record QueryUnderstanding(
        String originalQuery,
        String intent,
        List<SubQuery> subQueries,
        List<EntityRef> entities,
        Map<String, Object> scope,
        List<String> keywords,
        EvidenceNeed evidenceNeed,
        List<String> ambiguities,
        String source
) {
    public QueryUnderstanding {
        if (intent == null) intent = "general";
        if (subQueries == null) subQueries = List.of();
        if (entities == null) entities = List.of();
        if (scope == null) scope = Map.of();
        if (keywords == null) keywords = List.of();
        if (evidenceNeed == null) evidenceNeed = EvidenceNeed.empty();
        if (ambiguities == null) ambiguities = List.of();
        if (source == null) source = "rule";
    }
}
