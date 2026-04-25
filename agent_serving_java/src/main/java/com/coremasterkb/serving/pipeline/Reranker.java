package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.QueryPlan;
import com.coremasterkb.serving.domain.RetrievalCandidate;

import java.util.List;

/**
 * Reranker SPI — post-fusion candidate reordering.
 */
public interface Reranker {

    /**
     * Rerank candidates according to the query plan.
     *
     * @param candidates fused candidates
     * @param plan       query plan providing desired roles, block types, budget
     * @return reranked, truncated candidates
     */
    List<RetrievalCandidate> rerank(List<RetrievalCandidate> candidates, QueryPlan plan);
}
