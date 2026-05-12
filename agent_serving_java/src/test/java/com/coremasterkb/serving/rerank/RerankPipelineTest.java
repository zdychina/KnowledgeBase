package com.coremasterkb.serving.rerank;

import com.coremasterkb.serving.domain.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@DisplayName("RerankPipeline")
class RerankPipelineTest {

    private Reranker modelReranker;
    private Reranker llmReranker;
    private ScoreReranker scoreReranker;

    @BeforeEach
    void setUp() {
        modelReranker = mock(Reranker.class);
        llmReranker = mock(Reranker.class);
        scoreReranker = new ScoreReranker();
    }

    @Nested
    @DisplayName("empty input")
    class EmptyInput {
        @Test
        @DisplayName("null candidates returns empty")
        void nullReturnsEmpty() {
            var pipeline = new RerankPipeline(null, null, null);
            var result = pipeline.rerank(null, null, null);
            assertThat(result.candidates()).isEmpty();
            assertThat(result.traces()).isEmpty();
        }

        @Test
        @DisplayName("empty candidates returns empty")
        void emptyReturnsEmpty() {
            var pipeline = new RerankPipeline(null, null, null);
            var result = pipeline.rerank(List.of(), null, null);
            assertThat(result.candidates()).isEmpty();
            assertThat(result.traces()).isEmpty();
        }
    }

    @Nested
    @DisplayName("3-level cascade")
    class ThreeLevelCascade {
        @Test
        @DisplayName("model succeeds → used directly")
        void modelSucceeds() {
            var c1 = candidate("u1", 0.9);
            var c2 = candidate("u2", 0.7);
            when(modelReranker.rerank(any(), any())).thenReturn(List.of(c2, c1));

            var pipeline = new RerankPipeline(modelReranker, llmReranker, scoreReranker);
            var routePlan = new RetrievalRoutePlan(null, null, null,
                    new RerankConfig("model", "score"), null, null);

            var result = pipeline.rerank(List.of(c1, c2), routePlan, null);
            assertThat(result.candidates()).hasSize(2);
            assertThat(result.traces()).hasSize(1); // only model trace
            assertThat(result.traces().get(0).provider()).isEqualTo("model");
            assertThat(result.traces().get(0).succeeded()).isTrue();
        }

        @Test
        @DisplayName("model fails → score fallback")
        void modelFailsScoreFallback() {
            var c1 = candidate("u1", 0.9);
            when(modelReranker.rerank(any(), any())).thenThrow(new RuntimeException("fail"));

            var pipeline = new RerankPipeline(modelReranker, llmReranker, scoreReranker);
            var routePlan = new RetrievalRoutePlan(null, null, null,
                    new RerankConfig("score", "score"), null, null);

            var result = pipeline.rerank(List.of(c1), routePlan, null);
            assertThat(result.candidates()).hasSize(1);
            // model trace (failed) + score trace (succeeded)
            assertThat(result.traces()).hasSizeGreaterThanOrEqualTo(1);
        }

        @Test
        @DisplayName("model returns null → score fallback")
        void modelReturnsNullScoreFallback() {
            var c1 = candidate("u1", 0.9);
            when(modelReranker.rerank(any(), any())).thenReturn(null);

            var pipeline = new RerankPipeline(modelReranker, null, scoreReranker);
            var result = pipeline.rerank(List.of(c1), null, null);
            assertThat(result.candidates()).hasSize(1);
        }

        @Test
        @DisplayName("no model/llm → score only")
        void noModelScoreOnly() {
            var c1 = candidate("u1", 0.3);
            var c2 = candidate("u2", 0.9);

            var pipeline = new RerankPipeline(null, null, scoreReranker);
            var result = pipeline.rerank(List.of(c1, c2), null, null);
            assertThat(result.candidates()).hasSize(2);
            assertThat(result.candidates().get(0).retrievalUnitId()).isEqualTo("u2");
        }
    }

    @Nested
    @DisplayName("threshold filter")
    class ThresholdFilter {
        @Test
        @DisplayName("candidates with score < 0.01 are filtered out")
        void lowScoreFiltered() {
            var c1 = candidate("u1", 0.001);
            var c2 = candidate("u2", 0.9);

            var pipeline = new RerankPipeline(null, null, scoreReranker);
            var result = pipeline.rerank(List.of(c1, c2), null, null);
            assertThat(result.candidates()).hasSize(1);
            assertThat(result.candidates().get(0).retrievalUnitId()).isEqualTo("u2");
        }

        @Test
        @DisplayName("candidate with score exactly 0.01 is kept")
        void exactThresholdKept() {
            var c1 = candidate("u1", 0.01);

            var pipeline = new RerankPipeline(null, null, scoreReranker);
            var result = pipeline.rerank(List.of(c1), null, null);
            assertThat(result.candidates()).hasSize(1);
        }
    }

    @Nested
    @DisplayName("truncation")
    class Truncation {
        @Test
        @DisplayName("truncated to maxItems from route plan")
        void truncatedToMaxItems() {
            List<RetrievalCandidate> candidates = new ArrayList<>();
            for (int i = 0; i < 20; i++) {
                candidates.add(candidate("u" + i, 1.0 - i * 0.01));
            }

            var pipeline = new RerankPipeline(null, null, scoreReranker);
            var routePlan = new RetrievalRoutePlan(null, null, null, null,
                    new AssemblyConfig(false, false, 5, 5, 2, List.of()), null);

            var result = pipeline.rerank(candidates, routePlan, null);
            assertThat(result.candidates()).hasSize(5);
        }
    }

    @Nested
    @DisplayName("score chain annotation")
    class ScoreChainAnnotation {
        @Test
        @DisplayName("rerank score annotated into score chain")
        void rerankScoreAnnotated() {
            var c1 = candidate("u1", 0.9);

            var pipeline = new RerankPipeline(null, null, scoreReranker);
            var result = pipeline.rerank(List.of(c1), null, null);
            assertThat(result.candidates().get(0).scoreChain()).isNotNull();
            assertThat(result.candidates().get(0).scoreChain().rerankScore()).isEqualTo(0.9);
        }
    }

    private RetrievalCandidate candidate(String id, double score) {
        return new RetrievalCandidate(id, score, "bm25", null, null);
    }
}
