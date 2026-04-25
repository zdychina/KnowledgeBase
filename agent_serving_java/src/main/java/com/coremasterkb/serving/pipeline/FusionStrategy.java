package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.QueryPlan;
import com.coremasterkb.serving.domain.RetrievalCandidate;

import java.util.List;

/**
 * Fusion strategy SPI — merges candidates from multiple retrievers.
 */
public interface FusionStrategy {

    /**
     * Fuse and deduplicate candidates.
     *
     * @param candidates raw candidates from all retrievers
     * @param plan       query plan (may influence fusion parameters)
     * @return fused, deduplicated candidate list sorted by score descending
     */
    List<RetrievalCandidate> fuse(List<RetrievalCandidate> candidates, QueryPlan plan);
}
