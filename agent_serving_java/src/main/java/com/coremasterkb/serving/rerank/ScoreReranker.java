package com.coremasterkb.serving.rerank;

import com.coremasterkb.serving.domain.QueryUnderstanding;
import com.coremasterkb.serving.domain.RetrievalCandidate;

import java.util.Comparator;
import java.util.List;

/**
 * Score-based fallback reranker.
 *
 * <p>Sorts candidates by their existing score in descending order.
 * Always succeeds — never returns {@code null}.
 */
public class ScoreReranker implements Reranker {

    @Override
    public List<RetrievalCandidate> rerank(List<RetrievalCandidate> candidates, QueryUnderstanding understanding) {
        if (candidates == null || candidates.isEmpty()) {
            return List.of();
        }
        return candidates.stream()
                .sorted(Comparator.comparingDouble(RetrievalCandidate::score).reversed())
                .toList();
    }
}
