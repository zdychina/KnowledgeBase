package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.QueryPlan;
import com.coremasterkb.serving.domain.RetrievalCandidate;

import java.util.*;

/**
 * Reciprocal Rank Fusion (RRF).
 * Translated from pipeline/fusion.py (RRFFusion).
 *
 * Algorithm:
 *   1. Group candidates by source retriever.
 *   2. Within each source, assign rank (1-based, highest-score = rank 1).
 *   3. RRF score for each doc = sum(1 / (k + rank)) across all sources.
 *   4. Sort by RRF score descending.
 */
public class RRFFusion implements FusionStrategy {

    @Override
    public List<RetrievalCandidate> fuse(List<RetrievalCandidate> candidates, QueryPlan plan) {
        if (candidates == null || candidates.isEmpty()) {
            return Collections.emptyList();
        }

        int k = plan.retrieverConfig().rrfK();

        // Group by source
        Map<String, List<RetrievalCandidate>> bySource = new LinkedHashMap<>();
        for (RetrievalCandidate c : candidates) {
            bySource.computeIfAbsent(c.source(), s -> new ArrayList<>()).add(c);
        }

        // Sort each source group by score descending
        for (List<RetrievalCandidate> group : bySource.values()) {
            group.sort(Comparator.comparingDouble(RetrievalCandidate::score).reversed());
        }

        // Accumulate RRF scores per document id
        Map<String, Double> rrfScores = new LinkedHashMap<>();
        // Keep a representative candidate for each id (first seen wins for metadata)
        Map<String, RetrievalCandidate> representatives = new LinkedHashMap<>();

        for (List<RetrievalCandidate> group : bySource.values()) {
            for (int rank = 0; rank < group.size(); rank++) {
                RetrievalCandidate c = group.get(rank);
                String id = c.retrievalUnitId();
                if (id == null) continue;
                double contribution = 1.0 / (k + rank + 1); // rank is 0-based; +1 → 1-based
                rrfScores.merge(id, contribution, Double::sum);
                representatives.putIfAbsent(id, c);
            }
        }

        // Build result list with RRF score
        List<RetrievalCandidate> result = new ArrayList<>();
        for (Map.Entry<String, Double> entry : rrfScores.entrySet()) {
            String id = entry.getKey();
            double score = entry.getValue();
            RetrievalCandidate rep = representatives.get(id);
            result.add(rep.withScore(score));
        }

        // Sort descending by RRF score
        result.sort(Comparator.comparingDouble(RetrievalCandidate::score).reversed());
        return result;
    }
}
