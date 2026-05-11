package com.coremasterkb.serving.domain;

import java.util.List;

/**
 * Tracks the score progression of a candidate through the retrieval pipeline.
 *
 * @param rawScore     initial retrieval score
 * @param fusionScore  score after fusion
 * @param rerankScore  score after reranking
 * @param routeSources which routes contributed to this candidate; defaults to empty list
 */
public record ScoreChain(
        double rawScore,
        double fusionScore,
        double rerankScore,
        List<String> routeSources
) {
    public ScoreChain {
        if (routeSources == null) routeSources = List.of();
    }
}
