package com.coremasterkb.serving.domain;

import com.fasterxml.jackson.annotation.JsonProperty;

public record RerankerConfig(
        @JsonProperty("reranker_type") String rerankerType
) {
    /** Default config matching Python defaults. */
    public RerankerConfig() {
        this("score");
    }
}
