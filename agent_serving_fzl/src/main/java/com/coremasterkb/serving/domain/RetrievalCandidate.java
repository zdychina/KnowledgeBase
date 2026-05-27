package com.coremasterkb.serving.domain;

import java.util.Map;

/**
 * A single candidate result from the retrieval pipeline.
 * Immutable: with* methods return new instances.
 *
 * @param retrievalUnitId identifier of the underlying retrieval unit
 * @param score           current score
 * @param source          route or stage that produced this candidate
 * @param metadata        arbitrary metadata; defaults to empty map
 * @param scoreChain      score progression through the pipeline
 */
public record RetrievalCandidate(
        String retrievalUnitId,
        double score,
        String source,
        Map<String, Object> metadata,
        ScoreChain scoreChain
) {
    public RetrievalCandidate {
        if (metadata == null) metadata = Map.of();
    }

    public RetrievalCandidate withScore(double newScore) {
        return new RetrievalCandidate(retrievalUnitId, newScore, source, metadata, scoreChain);
    }

    public RetrievalCandidate withSource(String newSource) {
        return new RetrievalCandidate(retrievalUnitId, score, newSource, metadata, scoreChain);
    }

    public RetrievalCandidate withScoreChain(ScoreChain newScoreChain) {
        return new RetrievalCandidate(retrievalUnitId, score, source, metadata, newScoreChain);
    }
}
