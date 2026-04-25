package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.QueryPlan;
import com.coremasterkb.serving.domain.RetrievalCandidate;

import java.util.*;

/**
 * Identity fusion: dedup by id keeping the highest score, then sort descending.
 * Translated from pipeline/fusion.py (IdentityFusion).
 */
public class IdentityFusion implements FusionStrategy {

    @Override
    public List<RetrievalCandidate> fuse(List<RetrievalCandidate> candidates, QueryPlan plan) {
        if (candidates == null || candidates.isEmpty()) {
            return Collections.emptyList();
        }

        // Dedup by id, keeping the highest score
        Map<String, RetrievalCandidate> best = new LinkedHashMap<>();
        for (RetrievalCandidate c : candidates) {
            String id = c.retrievalUnitId();
            if (id == null) continue;
            best.merge(id, c, (existing, incoming) ->
                    incoming.score() > existing.score() ? incoming : existing);
        }

        // Sort by score descending
        List<RetrievalCandidate> result = new ArrayList<>(best.values());
        result.sort(Comparator.comparingDouble(RetrievalCandidate::score).reversed());
        return result;
    }
}
