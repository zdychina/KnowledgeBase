package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("WeightedRRFFusion")
class WeightedRRFFusionTest {

    private WeightedRRFFusion fusion;

    @BeforeEach
    void setUp() {
        fusion = new WeightedRRFFusion();
    }

    @Test
    @DisplayName("null candidates returns empty")
    void nullReturnsEmpty() {
        assertThat(fusion.fuse(null, null)).isEmpty();
    }

    @Test
    @DisplayName("empty candidates returns empty")
    void emptyReturnsEmpty() {
        assertThat(fusion.fuse(List.of(), null)).isEmpty();
    }

    @Test
    @DisplayName("weighted score is applied from route config")
    void weightedScoreApplied() {
        var c1 = candidate("u1", 0.9, "bm25");
        var c2 = candidate("u2", 0.8, "dense");

        var routePlan = new RetrievalRoutePlan(
                List.of(
                        new RouteConfig("bm25", true, 1.5, 50),
                        new RouteConfig("dense", true, 0.5, 50)
                ),
                null, new FusionConfig("weighted_rrf", 60), null, null, null
        );

        var result = fusion.fuse(List.of(c1, c2), routePlan);
        assertThat(result).hasSize(2);

        // bm25 with weight 1.5 should rank u1 higher than dense with 0.5
        assertThat(result.get(0).retrievalUnitId()).isEqualTo("u1");
    }

    @Test
    @DisplayName("same candidate in two sources gets combined weighted score")
    void sameCandidateTwoSourcesCombined() {
        var c1 = candidate("u1", 0.9, "bm25");
        var c2 = candidate("u1", 0.8, "dense");

        var routePlan = new RetrievalRoutePlan(
                List.of(
                        new RouteConfig("bm25", true, 1.0, 50),
                        new RouteConfig("dense", true, 1.0, 50)
                ),
                null, new FusionConfig("weighted_rrf", 60), null, null, null
        );

        var result = fusion.fuse(List.of(c1, c2), routePlan);
        assertThat(result).hasSize(1);
        assertThat(result.get(0).retrievalUnitId()).isEqualTo("u1");
    }

    @Test
    @DisplayName("ScoreChain updated with fusion score and route sources")
    void scoreChainUpdated() {
        var c1 = candidate("u1", 0.9, "bm25");

        var routePlan = new RetrievalRoutePlan(
                List.of(new RouteConfig("bm25", true, 1.0, 50)),
                null, new FusionConfig("weighted_rrf", 60), null, null, null
        );

        var result = fusion.fuse(List.of(c1), routePlan);
        assertThat(result).hasSize(1);

        var updated = result.get(0);
        assertThat(updated.scoreChain()).isNotNull();
        assertThat(updated.scoreChain().fusionScore()).isGreaterThan(0);
        assertThat(updated.scoreChain().routeSources()).contains("bm25");
    }

    @Test
    @DisplayName("no route plan defaults weight to 1.0")
    void noRoutePlanDefaultsWeight() {
        var c1 = candidate("u1", 0.9, "bm25");
        var c2 = candidate("u1", 0.8, "dense");

        // null routePlan → both get weight 1.0
        var result = fusion.fuse(List.of(c1, c2), null);
        assertThat(result).hasSize(1);
    }

    private RetrievalCandidate candidate(String id, double score, String source) {
        return new RetrievalCandidate(id, score, source, null, null);
    }
}
