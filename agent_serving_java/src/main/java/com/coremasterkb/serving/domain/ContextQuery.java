package com.coremasterkb.serving.domain;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public record ContextQuery(
        @JsonProperty("original") String original,
        @JsonProperty("normalized") String normalized,
        @JsonProperty("intent") String intent,
        @JsonProperty("entities") List<EntityRef> entities,
        @JsonProperty("scope") Map<String, Object> scope,
        @JsonProperty("keywords") List<String> keywords
) {
    public ContextQuery {
        if (entities == null) entities = new ArrayList<>();
        if (scope == null) scope = new HashMap<>();
        if (keywords == null) keywords = new ArrayList<>();
    }
}
