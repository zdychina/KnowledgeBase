package com.coremasterkb.serving.domain;

import java.util.List;
import java.util.Map;

/**
 * Structured query object passed to the retrieval layer.
 *
 * @param originalQuery  the raw user query
 * @param keywords       extracted keywords; defaults to empty list
 * @param entities       recognized entities; defaults to empty list
 * @param queryEmbedding pre-computed query embedding; may be null
 * @param subQueries     sub-query texts; defaults to empty list
 * @param intent         inferred intent; defaults to "general"
 * @param scope          scope constraints; defaults to empty map
 */
public record RetrievalQuery(
        String originalQuery,
        List<String> keywords,
        List<EntityRef> entities,
        float[] queryEmbedding,
        List<String> subQueries,
        String intent,
        Map<String, Object> scope
) {
    public RetrievalQuery {
        if (keywords == null) keywords = List.of();
        if (entities == null) entities = List.of();
        if (subQueries == null) subQueries = List.of();
        if (intent == null) intent = "general";
        if (scope == null) scope = Map.of();
    }
}
