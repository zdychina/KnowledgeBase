package com.coremasterkb.serving.domain;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

public record RetrieverConfig(
        @JsonProperty("enabled_retrievers") List<String> enabledRetrievers,
        @JsonProperty("fusion_method") String fusionMethod,
        @JsonProperty("rrf_k") int rrfK,
        @JsonProperty("retriever_weights") Map<String, Double> retrieverWeights
) {
    /** Default: fts_bm25 only, identity fusion, no explicit weights. */
    public RetrieverConfig() {
        this(List.of("fts_bm25"), "identity", 60, Map.of());
    }
}
