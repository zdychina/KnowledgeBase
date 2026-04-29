package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.QueryPlan;
import com.coremasterkb.serving.domain.RetrievalCandidate;

import java.util.*;

/**
 * Weighted Reciprocal Rank Fusion (WRRF).
 *
 * Extends plain RRF by scaling each source's contribution by a per-source weight:
 *   score(doc) = Σ_source  weight(source) / (k + rank(doc, source) + 1)
 *
 * Weights are read from QueryPlan.retrieverConfig().retrieverWeights().
 * Sources absent from the weight map default to 1.0.
 */
public class WeightedRRFFusion implements FusionStrategy {

    @Override
    public List<RetrievalCandidate> fuse(List<RetrievalCandidate> candidates, QueryPlan plan) {
        if (candidates == null || candidates.isEmpty()) return Collections.emptyList();

        int k = plan.retrieverConfig().rrfK();
        Map<String, Double> weights = plan.retrieverConfig().retrieverWeights();

        // Group by source, sort each group by score descending
        Map<String, List<RetrievalCandidate>> bySource = new LinkedHashMap<>();
        for (RetrievalCandidate c : candidates) {
            bySource.computeIfAbsent(c.source(), s -> new ArrayList<>()).add(c);
        }
        for (List<RetrievalCandidate> group : bySource.values()) {
            group.sort(Comparator.comparingDouble(RetrievalCandidate::score).reversed());
        }

        // Accumulate weighted RRF scores
        Map<String, Double> rrfScores         = new LinkedHashMap<>();
        Map<String, RetrievalCandidate> repMap = new LinkedHashMap<>();

        for (Map.Entry<String, List<RetrievalCandidate>> entry : bySource.entrySet()) {
            String source = entry.getKey();
            double weight = weights.getOrDefault(source, 1.0);
            List<RetrievalCandidate> group = entry.getValue();

            for (int rank = 0; rank < group.size(); rank++) {
                RetrievalCandidate c = group.get(rank);
                String id = c.retrievalUnitId();
                if (id == null) continue;
                double contribution = weight / (k + rank + 1);
                rrfScores.merge(id, contribution, Double::sum);
                repMap.putIfAbsent(id, c);
            }
        }

        // Build result list
        List<RetrievalCandidate> result = new ArrayList<>();
        for (Map.Entry<String, Double> e : rrfScores.entrySet()) {
            RetrievalCandidate rep = repMap.get(e.getKey());
            result.add(rep.withScore(e.getValue()));
        }

        result.sort(Comparator.comparingDouble(RetrievalCandidate::score).reversed());
        return result;
    }
}
