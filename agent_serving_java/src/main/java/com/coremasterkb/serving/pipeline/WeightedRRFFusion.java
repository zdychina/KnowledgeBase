package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.FusionConfig;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.RetrievalRoutePlan;
import com.coremasterkb.serving.domain.RouteConfig;
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
 * Weighted Reciprocal Rank Fusion.
 *
 * <p>Same as RRF but each route's contribution is multiplied by its configured weight:
 * {@code score = sum(weight_j / (k + rank_j))} where weight_j comes from
 * {@link RouteConfig#weight()}.</p>
 *
 * <p>Each candidate's {@link ScoreChain} is updated with the computed fusion score
 * and the set of route sources that contributed to it.</p>
 */
public class WeightedRRFFusion implements FusionStrategy {

    private static final int DEFAULT_K = 60;

    @Override
    public List<RetrievalCandidate> fuse(List<RetrievalCandidate> candidates, RetrievalRoutePlan routePlan) {
        if (candidates == null || candidates.isEmpty()) {
            return List.of();
        }

        int k = resolveK(routePlan);

        // Build weight map from route plan
        Map<String, Double> weightMap = new HashMap<>();
        if (routePlan != null && routePlan.routes() != null) {
            for (var route : routePlan.routes()) {
                weightMap.put(route.name(), route.weight());
            }
        }

        // Group candidates by source route
        Map<String, List<RetrievalCandidate>> bySource = new LinkedHashMap<>();
        for (var c : candidates) {
            bySource.computeIfAbsent(c.source(), s -> new ArrayList<>()).add(c);
        }

        // Sort each source group by original score descending
        for (var group : bySource.values()) {
            group.sort(Comparator.comparingDouble(RetrievalCandidate::score).reversed());
        }

        // Compute weighted RRF scores and track route sources per candidate
        Map<String, Double> rrfScores = new HashMap<>();
        Map<String, RetrievalCandidate> candidateMap = new LinkedHashMap<>();
        Map<String, Set<String>> candidateSources = new HashMap<>();

        for (var entry : bySource.entrySet()) {
            String source = entry.getKey();
            double weight = weightMap.getOrDefault(source, 1.0);
            List<RetrievalCandidate> ranked = entry.getValue();

            for (int i = 0; i < ranked.size(); i++) {
                var c = ranked.get(i);
                int rank = i + 1; // 1-based rank
                String uid = c.retrievalUnitId();
                rrfScores.merge(uid, weight / (k + rank), Double::sum);
                candidateMap.putIfAbsent(uid, c);
                candidateSources.computeIfAbsent(uid, u -> new LinkedHashSet<>()).add(source);
            }
        }

        // Build results with updated score and score chain
        return rrfScores.entrySet().stream()
                .sorted(Map.Entry.<String, Double>comparingByValue(Comparator.reverseOrder()))
                .map(e -> {
                    String uid = e.getKey();
                    double fusionScore = e.getValue();
                    var original = candidateMap.get(uid);
                    List<String> sources = List.copyOf(candidateSources.getOrDefault(uid, Set.of()));

                    // Build or update score chain
                    var chain = original.scoreChain() != null
                            ? original.scoreChain()
                            : new ScoreChain(original.score(), 0.0, 0.0, List.of(original.source()));
                    chain = chain.withFusionScore(fusionScore).withRouteSources(sources);

                    return original.withScore(fusionScore).withScoreChain(chain);
                })
                .toList();
    }

    private int resolveK(RetrievalRoutePlan routePlan) {
        if (routePlan != null) {
            FusionConfig fusion = routePlan.fusion();
            if (fusion != null) {
                return fusion.k();
            }
        }
        return DEFAULT_K;
    }
}
