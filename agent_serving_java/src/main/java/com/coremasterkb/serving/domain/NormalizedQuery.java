package com.coremasterkb.serving.domain;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record NormalizedQuery(
        @JsonProperty("original_query") String originalQuery,
        @JsonProperty("intent") String intent,
        @JsonProperty("entities") List<EntityRef> entities,
        @JsonProperty("scope") Map<String, Object> scope,
        @JsonProperty("keywords") List<String> keywords,
        @JsonProperty("desired_roles") List<String> desiredRoles
) {
    public NormalizedQuery {
        if (originalQuery == null) originalQuery = "";
        if (intent == null) intent = "general";
        if (entities == null) entities = new ArrayList<>();
        if (scope == null) scope = new HashMap<>();
        if (keywords == null) keywords = new ArrayList<>();
        if (desiredRoles == null) desiredRoles = new ArrayList<>();
    }

    public NormalizedQuery withScope(Map<String, Object> newScope) {
        return new NormalizedQuery(originalQuery, intent, entities, newScope, keywords, desiredRoles);
    }

    public NormalizedQuery withEntities(List<EntityRef> newEntities) {
        return new NormalizedQuery(originalQuery, intent, newEntities, scope, keywords, desiredRoles);
    }
}