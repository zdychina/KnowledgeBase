package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.FusionConfig;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.RetrievalRoutePlan;
import com.coremasterkb.serving.domain.ScoreChain;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

@DisplayName("RRFFusion")
class RRFFusionTest {

    private RRFFusion fusion;

    @BeforeEach
    void setUp() {
        fusion = new RRFFusion();
    }

    @Nested
    @DisplayName("empty / null input")
    class EmptyInput {
        @Test
        @DisplayName("null candidates returns empty list")
        void nullReturnsEmpty() {
            assertThat(fusion.fuse(null, null)).isEmpty();
        }

        @Test
        @DisplayName("empty candidates returns empty list")
        void emptyReturnsEmpty() {
            assertThat(fusion.fuse(List.of(), null)).isEmpty();
        }
    }

    @Nested
    @DisplayName("single source")
    class SingleSource {
        @Test
        @DisplayName("single candidate returns itself")
        void singleCandidate() {
            var c = candidate("u1", 0.9, "bm25");
            var result = fusion.fuse(List.of(c), null);
            assertThat(result).hasSize(1);
            assertThat(result.get(0).retrievalUnitId()).isEqualTo("u1");
        }

        @Test
        @DisplayName("candidates sorted by score within single source")
        void sortedByScoreWithinSource() {
            var c1 = candidate("u1", 0.5, "bm25");
            var c2 = candidate("u2", 0.9, "bm25");
            var c3 = candidate("u3", 0.7, "bm25");
            var result = fusion.fuse(List.of(c1, c2, c3), null);
            assertThat(result).hasSize(3);
            assertThat(result.get(0).retrievalUnitId()).isEqualTo("u2");
        }
    }

    @Nested
    @DisplayName("multi-source RRF formula")
    class MultiSource {
        @Test
        @DisplayName("same candidate in two sources gets combined RRF score")
        void sameCandidateTwoSources() {
            int k = 60;
            var c1 = candidate("u1", 0.9, "bm25");
            var c2 = candidate("u1", 0.8, "dense");
            // Both rank 1 in their respective sources
            // RRF score = 1/(k+1) + 1/(k+1) = 2/61
            var routePlan = new RetrievalRoutePlan(
                    List.of(), null, new FusionConfig("rrf", k), null, null, null);
            var result = fusion.fuse(List.of(c1, c2), routePlan);
            assertThat(result).hasSize(1);
        }

        @Test
        @DisplayName("custom k parameter is respected")
        void customKParameter() {
            int k = 10;
            var c1 = candidate("u1", 0.9, "bm25");
            var c2 = candidate("u1", 0.8, "dense");
            var routePlan = new RetrievalRoutePlan(
                    List.of(), null, new FusionConfig("rrf", k), null, null, null);
            var result = fusion.fuse(List.of(c1, c2), routePlan);
            assertThat(result).hasSize(1);
        }

        @Test
        @DisplayName("different candidates across sources deduplicated")
        void differentCandidatesDeduplicated() {
            var c1 = candidate("u1", 0.9, "bm25");
            var c2 = candidate("u2", 0.8, "bm25");
            var c3 = candidate("u1", 0.7, "dense");
            var result = fusion.fuse(List.of(c1, c2, c3), null);
            assertThat(result).hasSize(2);
            // u1 appears in both sources, should rank higher
            assertThat(result.get(0).retrievalUnitId()).isEqualTo("u1");
        }
    }

    private RetrievalCandidate candidate(String id, double score, String source) {
        return new RetrievalCandidate(id, score, source, null, null);
    }
}
