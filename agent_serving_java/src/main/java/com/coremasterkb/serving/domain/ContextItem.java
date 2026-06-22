package com.coremasterkb.serving.domain;

import java.util.List;
import java.util.Map;

/**
 * A single context item assembled for evidence delivery.
 *
 * @param id              unique item identifier
 * @param kind            item kind (e.g. "retrieval_unit", "raw_segment")
 * @param role            context role (e.g. "seed", "context", "support")
 * @param text            the actual text content
 * @param score           relevance score
 * @param title           document / section title
 * @param blockType       block type; defaults to "unknown"
 * @param semanticRole    semantic role; defaults to "unknown"
 * @param sourceId        source document identifier
 * @param relationToSeed  relation to the seed item
 * @param sourceRefs      source references; defaults to empty map
 * @param metadata        additional metadata; defaults to empty map
 * @param routeSources    which routes contributed; defaults to empty list
 * @param scoreChain      score progression through the pipeline
 * @param evidenceRole    evidence role classification; defaults to ""
 * @param citation        citation metadata; defaults to empty map
 */
public record ContextItem(
        String id,
        String kind,
        String role,
        String text,
        double score,
        String title,
        String blockType,
        String semanticRole,
        String sourceId,
        String relationToSeed,
        Map<String, Object> sourceRefs,
        Map<String, Object> metadata,
        List<String> routeSources,
        ScoreChain scoreChain,
        String evidenceRole,
        Map<String, Object> citation
) {
    public ContextItem {
        if (blockType == null) blockType = "unknown";
        if (semanticRole == null) semanticRole = "unknown";
        if (sourceRefs == null) sourceRefs = Map.of();
        if (metadata == null) metadata = Map.of();
        if (routeSources == null) routeSources = List.of();
        if (evidenceRole == null) evidenceRole = "";
        if (citation == null) citation = Map.of();
    }
}
