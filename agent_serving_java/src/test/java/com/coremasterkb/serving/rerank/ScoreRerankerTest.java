package com.coremasterkb.serving.rerank;

import com.coremasterkb.serving.domain.QueryUnderstanding;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("ScoreReranker")
class ScoreRerankerTest {

    private ScoreReranker reranker;

    @BeforeEach
    void setUp() {
        reranker = new ScoreReranker();
    }

    @Test
    @DisplayName("null input returns empty list")
    void nullReturnsEmpty() {
        assertThat(reranker.rerank(null, null)).isEmpty();
    }

    @Test
    @DisplayName("empty input returns empty list")
    void emptyReturnsEmpty() {
        assertThat(reranker.rerank(List.of(), null)).isEmpty();
    }

    @Test
    @DisplayName("sorts candidates by score descending")
    void sortByScoreDescending() {
        var c1 = new RetrievalCandidate("u1", 0.3, "bm25", null, null);
        var c2 = new RetrievalCandidate("u2", 0.9, "bm25", null, null);
        var c3 = new RetrievalCandidate("u3", 0.5, "dense", null, null);

        var result = reranker.rerank(List.of(c1, c2, c3), null);
        assertThat(result).hasSize(3);
        assertThat(result.get(0).retrievalUnitId()).isEqualTo("u2");
        assertThat(result.get(1).retrievalUnitId()).isEqualTo("u3");
        assertThat(result.get(2).retrievalUnitId()).isEqualTo("u1");
    }

    @Test
    @DisplayName("already sorted list stays sorted")
    void alreadySortedStaysSorted() {
        var c1 = new RetrievalCandidate("u1", 0.9, "bm25", null, null);
        var c2 = new RetrievalCandidate("u2", 0.5, "dense", null, null);

        var result = reranker.rerank(List.of(c1, c2), null);
        assertThat(result.get(0).retrievalUnitId()).isEqualTo("u1");
        assertThat(result.get(1).retrievalUnitId()).isEqualTo("u2");
    }
}
