package com.coremasterkb.serving.rerank;

import com.coremasterkb.serving.domain.QueryUnderstanding;
import com.coremasterkb.serving.domain.RetrievalCandidate;

import java.util.List;

/**
 * Reranker interface for post-retrieval candidate reordering.
 *
 * <p>Implementations may return {@code null} to signal failure,
 * allowing the pipeline to fall back to the next strategy.
 */
public interface Reranker {

    /**
     * Rerank candidates using the given query understanding.
     *
     * @param candidates   input candidates (may be in any order)
     * @param understanding query understanding for context
     * @return reranked candidates, or {@code null} if this reranker cannot produce a result
     */
    List<RetrievalCandidate> rerank(List<RetrievalCandidate> candidates, QueryUnderstanding understanding);
}
