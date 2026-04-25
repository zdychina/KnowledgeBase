package com.coremasterkb.serving.domain;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.HashMap;
import java.util.Map;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record SourceRef(
        @JsonProperty("id") String id,
        @JsonProperty("document_key") String documentKey,
        @JsonProperty("title") String title,
        @JsonProperty("relative_path") String relativePath,
        @JsonProperty("scope_json") Map<String, Object> scopeJson,
        @JsonProperty("metadata") Map<String, Object> metadata
) {
    public SourceRef {
        if (scopeJson == null) scopeJson = new HashMap<>();
        if (metadata == null) metadata = new HashMap<>();
    }
}
