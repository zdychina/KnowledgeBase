package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.RetrievalRoutePlan;
import java.util.List;

/**
 * Strategy interface for fusing candidates from multiple retrieval routes.
 */
public interface FusionStrategy {

    /**
     * Combine and rerank candidates from multiple retrieval routes.
     *
     * @param candidates candidates collected from all executed routes
     * @param routePlan  the route plan containing route configs and fusion parameters
     * @return fused and ranked candidates
     */
    List<RetrievalCandidate> fuse(List<RetrievalCandidate> candidates, RetrievalRoutePlan routePlan);
}
