package com.coremasterkb.serving.domain;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record RetrieverConfig(
        @JsonProperty("enabled_retrievers") List<String> enabledRetrievers,
        @JsonProperty("fusion_method") String fusionMethod,
        @JsonProperty("rrf_k") int rrfK
) {
    /** Default config matching Python defaults. */
    public RetrieverConfig() {
        this(List.of("fts_bm25"), "identity", 60);
    }
}
