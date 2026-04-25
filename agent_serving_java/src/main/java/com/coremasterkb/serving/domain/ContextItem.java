package com.coremasterkb.serving.domain;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.HashMap;
import java.util.Map;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record ContextItem(
        @JsonProperty("id") String id,
        @JsonProperty("kind") String kind,
        @JsonProperty("role") String role,
        @JsonProperty("text") String text,
        @JsonProperty("score") double score,
        @JsonProperty("title") String title,
        @JsonProperty("block_type") String blockType,
        @JsonProperty("semantic_role") String semanticRole,
        @JsonProperty("source_id") String sourceId,
        @JsonProperty("relation_to_seed") String relationToSeed,
        @JsonProperty("source_refs") Map<String, Object> sourceRefs,
        @JsonProperty("metadata") Map<String, Object> metadata
) {
    public ContextItem {
        if (blockType == null) blockType = "unknown";
        if (semanticRole == null) semanticRole = "unknown";
        if (sourceRefs == null) sourceRefs = new HashMap<>();
        if (metadata == null) metadata = new HashMap<>();
    }
}
