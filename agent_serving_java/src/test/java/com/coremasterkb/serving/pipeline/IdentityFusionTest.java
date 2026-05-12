package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.RetrievalCandidate;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("IdentityFusion")
class IdentityFusionTest {

    private IdentityFusion fusion;

    @BeforeEach
    void setUp() {
        fusion = new IdentityFusion();
    }

    @Nested
    @DisplayName("empty / null input")
    class EmptyInput {
        @Test
        @DisplayName("null returns empty")
        void nullReturnsEmpty() {
            assertThat(fusion.fuse(null, null)).isEmpty();
        }

        @Test
        @DisplayName("empty returns empty")
        void emptyReturnsEmpty() {
            assertThat(fusion.fuse(List.of(), null)).isEmpty();
        }
    }

    @Test
    @DisplayName("deduplicates by id keeping highest score")
    void dedupKeepsHighest() {
        var c1 = candidate("u1", 0.9, "bm25");
        var c2 = candidate("u1", 0.7, "dense"); // duplicate id, lower score
        var c3 = candidate("u2", 0.8, "bm25");

        var result = fusion.fuse(List.of(c1, c2, c3), null);
        assertThat(result).hasSize(2);
        // u1 with 0.9 should be kept over u1 with 0.7
        assertThat(result.stream().filter(c -> "u1".equals(c.retrievalUnitId())).findFirst())
                .isPresent()
                .get().extracting(RetrievalCandidate::score).isEqualTo(0.9);
    }

    @Test
    @DisplayName("sorted by score descending")
    void sortedByScoreDescending() {
        var c1 = candidate("u1", 0.3, "bm25");
        var c2 = candidate("u2", 0.9, "dense");
        var c3 = candidate("u3", 0.5, "bm25");

        var result = fusion.fuse(List.of(c1, c2, c3), null);
        assertThat(result).hasSize(3);
        assertThat(result.get(0).score()).isEqualTo(0.9);
        assertThat(result.get(1).score()).isEqualTo(0.5);
        assertThat(result.get(2).score()).isEqualTo(0.3);
    }

    @Test
    @DisplayName("all unique candidates preserved")
    void allUniquePreserved() {
        var c1 = candidate("u1", 0.9, "bm25");
        var c2 = candidate("u2", 0.8, "bm25");
        var c3 = candidate("u3", 0.7, "bm25");

        var result = fusion.fuse(List.of(c1, c2, c3), null);
        assertThat(result).hasSize(3);
    }

    private RetrievalCandidate candidate(String id, double score, String source) {
        return new RetrievalCandidate(id, score, source, null, null);
    }
}
