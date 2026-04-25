package com.coremasterkb.serving.domain;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record SearchRequest(
        @JsonProperty("query") String query,
        @JsonProperty("scope") Map<String, Object> scope,
        @JsonProperty("entities") List<EntityRef> entities,
        @JsonProperty("debug") boolean debug
) {
    public SearchRequest {
        if (query == null) query = "";
    }
}