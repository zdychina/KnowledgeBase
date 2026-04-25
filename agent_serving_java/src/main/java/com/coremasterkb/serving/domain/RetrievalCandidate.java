package com.coremasterkb.serving.domain;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.HashMap;
import java.util.Map;

public record RetrievalCandidate(
        @JsonProperty("retrieval_unit_id") String retrievalUnitId,
        @JsonProperty("score") double score,
        @JsonProperty("source") String source,
        @JsonProperty("metadata") Map<String, Object> metadata
) {
    public RetrievalCandidate {
        if (metadata == null) metadata = new HashMap<>();
    }

    /** Convenience: create with a new score (used in reranker). */
    public RetrievalCandidate withScore(double newScore) {
        return new RetrievalCandidate(retrievalUnitId, newScore, source, metadata);
    }
}
