package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.RetrievalRoutePlan;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Standard Reciprocal Rank Fusion (RRF).
 *
 * <p>Candidates are grouped by source route, ranked per-source by original score
 * descending, then merged via the RRF formula:
 * {@code score = sum(1 / (k + rank_i))} for each source ranking.</p>
 *
 * <p>Default k=60; can be overridden via {@code routePlan.fusion().k()}.</p>
 */
public class RRFFusion implements FusionStrategy {

    private static final int DEFAULT_K = 60;

    @Override
    public List<RetrievalCandidate> fuse(List<RetrievalCandidate> candidates, RetrievalRoutePlan routePlan) {
        if (candidates == null || candidates.isEmpty()) {
            return List.of();
        }

        int k = resolveK(routePlan);

        // Group candidates by source route
        Map<String, List<RetrievalCandidate>> bySource = new LinkedHashMap<>();
        for (var c : candidates) {
            bySource.computeIfAbsent(c.source(), s -> new ArrayList<>()).add(c);
        }

        // Sort each source group by original score descending
        for (var group : bySource.values()) {
            group.sort(Comparator.comparingDouble(RetrievalCandidate::score).reversed());
        }

        // Compute RRF scores: score += 1 / (k + rank) per source
        Map<String, Double> rrfScores = new HashMap<>();
        Map<String, RetrievalCandidate> candidateMap = new LinkedHashMap<>();

        for (var entry : bySource.entrySet()) {
            List<RetrievalCandidate> ranked = entry.getValue();
            for (int i = 0; i < ranked.size(); i++) {
                var c = ranked.get(i);
                int rank = i + 1; // 1-based rank
                String uid = c.retrievalUnitId();
                rrfScores.merge(uid, 1.0 / (k + rank), Double::sum);
                candidateMap.putIfAbsent(uid, c);
            }
        }

        // Sort by RRF score descending
        return rrfScores.entrySet().stream()
                .sorted(Map.Entry.<String, Double>comparingByValue(Comparator.reverseOrder()))
                .map(e -> candidateMap.get(e.getKey()))
                .toList();
    }

    private int resolveK(RetrievalRoutePlan routePlan) {
        if (routePlan != null && routePlan.fusion() != null) {
            return routePlan.fusion().k();
        }
        return DEFAULT_K;
    }
}
