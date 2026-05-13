package com.coremasterkb.serving.domain;

import java.util.List;
import java.util.Map;

/**
 * Structured query used in the context-assembly phase.
 *
 * @param original      raw user query
 * @param normalized    normalized / cleaned query text
 * @param intent        inferred intent
 * @param entities      recognized entities
 * @param scope         scope constraints
 * @param keywords      extracted keywords
 * @param source        query-understanding source: "llm" or "rule"
 * @param releaseId     release ID of the knowledge base snapshot that was searched
 * @param buildId       build ID of the knowledge base snapshot that was searched
 * @param snapshotCount number of document snapshots included in the search scope
 */
public record ContextQuery(
        String original,
        String normalized,
        String intent,
        List<EntityRef> entities,
        Map<String, Object> scope,
        List<String> keywords,
        String source,
        String releaseId,
        String buildId,
        int snapshotCount
) {
}
