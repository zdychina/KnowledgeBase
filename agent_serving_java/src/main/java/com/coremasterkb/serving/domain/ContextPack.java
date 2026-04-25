package com.coremasterkb.serving.domain;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record ContextPack(
        @JsonProperty("query") ContextQuery query,
        @JsonProperty("items") List<ContextItem> items,
        @JsonProperty("relations") List<ContextRelation> relations,
        @JsonProperty("sources") List<SourceRef> sources,
        @JsonProperty("issues") List<Issue> issues,
        @JsonProperty("suggestions") List<String> suggestions,
        @JsonProperty("debug") Map<String, Object> debug
) {
    public ContextPack {
        if (items == null) items = new ArrayList<>();
        if (relations == null) relations = new ArrayList<>();
        if (sources == null) sources = new ArrayList<>();
        if (issues == null) issues = new ArrayList<>();
        if (suggestions == null) suggestions = new ArrayList<>();
    }
}
