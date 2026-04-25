package com.coremasterkb.serving.domain;

import com.fasterxml.jackson.annotation.JsonProperty;

public record RetrievalBudget(
        @JsonProperty("max_items") int maxItems,
        @JsonProperty("max_expanded") int maxExpanded,
        @JsonProperty("recall_multiplier") int recallMultiplier
) {
    /** Default budget matching Python defaults. */
    public RetrievalBudget() {
        this(10, 20, 5);
    }
}
