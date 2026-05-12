package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.RetrievalRoutePlan;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;

/**
 * Pass-through fusion: deduplicates by retrievalUnitId keeping the highest score,
 * then sorts by score descending.
 */
public class IdentityFusion implements FusionStrategy {

    @Override
    public List<RetrievalCandidate> fuse(List<RetrievalCandidate> candidates, RetrievalRoutePlan routePlan) {
        if (candidates == null || candidates.isEmpty()) {
            return List.of();
        }

        // Deduplicate by retrievalUnitId, keeping the candidate with the highest score
        var seen = new LinkedHashMap<String, RetrievalCandidate>();
        for (var c : candidates) {
            var key = c.retrievalUnitId();
            var existing = seen.get(key);
            if (existing == null || c.score() > existing.score()) {
                seen.put(key, c);
            }
        }

        return seen.values().stream()
                .sorted(Comparator.comparingDouble(RetrievalCandidate::score).reversed())
                .toList();
    }
}
