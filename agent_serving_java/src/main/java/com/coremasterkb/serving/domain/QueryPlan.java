package com.coremasterkb.serving.domain;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public record QueryPlan(
        @JsonProperty("intent") String intent,
        @JsonProperty("keywords") List<String> keywords,
        @JsonProperty("entity_constraints") List<EntityRef> entityConstraints,
        @JsonProperty("scope_constraints") Map<String, Object> scopeConstraints,
        @JsonProperty("desired_roles") List<String> desiredRoles,
        @JsonProperty("desired_block_types") List<String> desiredBlockTypes,
        @JsonProperty("budget") RetrievalBudget budget,
        @JsonProperty("expansion") ExpansionConfig expansion,
        @JsonProperty("retriever_config") RetrieverConfig retrieverConfig,
        @JsonProperty("reranker_config") RerankerConfig rerankerConfig
) {
    public QueryPlan {
        if (intent == null) intent = "general";
        if (keywords == null) keywords = new ArrayList<>();
        if (entityConstraints == null) entityConstraints = new ArrayList<>();
        if (scopeConstraints == null) scopeConstraints = new HashMap<>();
        if (desiredRoles == null) desiredRoles = new ArrayList<>();
        if (desiredBlockTypes == null) desiredBlockTypes = new ArrayList<>();
        if (budget == null) budget = new RetrievalBudget();
        if (expansion == null) expansion = new ExpansionConfig();
        if (retrieverConfig == null) retrieverConfig = new RetrieverConfig();
        if (rerankerConfig == null) rerankerConfig = new RerankerConfig();
    }
}
