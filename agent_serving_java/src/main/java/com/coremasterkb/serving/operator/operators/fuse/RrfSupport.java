package com.coremasterkb.serving.operator.operators.fuse;

import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.ScoreChain;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Shared (weighted) Reciprocal Rank Fusion math, reimplemented for the operator system with the
 * same semantics as the existing {@code WeightedRRFFusion}: candidates are grouped by
 * {@code source} (route name), ranked per-source by original score (1-based), and combined as
 * {@code score = Σ weight_source / (k + rank)}. Weights default to 1.0 per source.
 */
final class RrfSupport {

    private RrfSupport() {}

    static List<RetrievalCandidate> fuse(
            List<RetrievalCandidate> candidates, int k, Map<String, Double> weightsBySource) {

        if (candidates == null || candidates.isEmpty()) {
            return List.of();
        }
        Map<String, Double> weights = weightsBySource != null ? weightsBySource : Map.of();

        // Group by source route
        Map<String, List<RetrievalCandidate>> bySource = new LinkedHashMap<>();
        for (RetrievalCandidate c : candidates) {
            bySource.computeIfAbsent(c.source(), s -> new ArrayList<>()).add(c);
        }
        for (List<RetrievalCandidate> group : bySource.values()) {
            group.sort(Comparator.comparingDouble(RetrievalCandidate::score).reversed());
        }

        Map<String, Double> rrf = new HashMap<>();
        Map<String, RetrievalCandidate> firstByUid = new LinkedHashMap<>();
        Map<String, Set<String>> sourcesByUid = new HashMap<>();

        for (var entry : bySource.entrySet()) {
            String source = entry.getKey();
            double weight = weights.getOrDefault(source, 1.0);
            List<RetrievalCandidate> ranked = entry.getValue();
            for (int i = 0; i < ranked.size(); i++) {
                RetrievalCandidate c = ranked.get(i);
                int rank = i + 1;
                String uid = c.retrievalUnitId();
                rrf.merge(uid, weight / (k + rank), Double::sum);
                firstByUid.putIfAbsent(uid, c);
                sourcesByUid.computeIfAbsent(uid, u -> new LinkedHashSet<>()).add(source);
            }
        }

        return rrf.entrySet().stream()
                .sorted(Map.Entry.<String, Double>comparingByValue(Comparator.reverseOrder()))
                .map(e -> {
                    String uid = e.getKey();
                    double fusionScore = e.getValue();
                    RetrievalCandidate original = firstByUid.get(uid);
                    List<String> sources = List.copyOf(sourcesByUid.getOrDefault(uid, Set.of()));
                    ScoreChain chain = original.scoreChain() != null
                            ? original.scoreChain()
                            : new ScoreChain(original.score(), 0.0, 0.0, List.of(original.source()));
                    chain = chain.withFusionScore(fusionScore).withRouteSources(sources);
                    return original.withScore(fusionScore).withScoreChain(chain);
                })
                .toList();
    }
}
