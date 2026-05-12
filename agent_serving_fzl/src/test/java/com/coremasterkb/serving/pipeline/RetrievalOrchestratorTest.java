package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.*;
import com.coremasterkb.serving.retrieval.Retriever;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

@DisplayName("RetrievalOrchestrator")
class RetrievalOrchestratorTest {

    private RetrievalOrchestrator orchestrator;
    private Retriever bm25Retriever;
    private Retriever denseRetriever;

    @BeforeEach
    void setUp() {
        bm25Retriever = mock(Retriever.class);
        denseRetriever = mock(Retriever.class);
        orchestrator = new RetrievalOrchestrator(Map.of(
                "lexical_bm25", bm25Retriever,
                "dense_vector", denseRetriever
        ));
    }

    @Nested
    @DisplayName("empty snapshotIds")
    class EmptySnapshotIds {
        @Test
        @DisplayName("null snapshotIds returns empty result")
        void nullReturnsEmpty() {
            var understanding = new QueryUnderstanding("q", "general", null, null, null, null, null, null, "rule");
            var plan = new RetrievalRoutePlan(List.of(), null, null, null, null, null);
            var result = orchestrator.execute(understanding, plan, null, null);
            assertThat(result.candidates()).isEmpty();
        }

        @Test
        @DisplayName("empty snapshotIds returns empty result")
        void emptyReturnsEmpty() {
            var understanding = new QueryUnderstanding("q", "general", null, null, null, null, null, null, "rule");
            var plan = new RetrievalRoutePlan(List.of(), null, null, null, null, null);
            var result = orchestrator.execute(understanding, plan, null, List.of());
            assertThat(result.candidates()).isEmpty();
        }
    }

    @Nested
    @DisplayName("dense route auto-skip")
    class DenseAutoSkip {
        @Test
        @DisplayName("dense_vector skipped when no embedding provided")
        void denseSkippedNoEmbedding() {
            when(bm25Retriever.retrieve(any(), any(), anyInt())).thenReturn(List.of());

            var understanding = new QueryUnderstanding("q", "general", null, null, null, null, null, null, "rule");
            var plan = new RetrievalRoutePlan(
                    List.of(
                            new RouteConfig("lexical_bm25", true, 1.0, 50),
                            new RouteConfig("dense_vector", true, 0.9, 50)
                    ),
                    null, null, null, null, null
            );

            var result = orchestrator.execute(understanding, plan, null, List.of("snap1"));

            // dense should be skipped with "no_embedding" reason
            assertThat(result.routeTraces()).hasSize(2);
            var denseTrace = result.routeTraces().stream()
                    .filter(t -> "dense_vector".equals(t.name())).findFirst();
            assertThat(denseTrace).isPresent();
            assertThat(denseTrace.get().attempted()).isFalse();
            assertThat(denseTrace.get().skippedReason()).isEqualTo("no_embedding");
        }

        @Test
        @DisplayName("dense_vector runs when embedding is provided")
        void denseRunWithEmbedding() {
            when(bm25Retriever.retrieve(any(), any(), anyInt())).thenReturn(List.of());
            when(denseRetriever.retrieve(any(), any(), anyInt())).thenReturn(List.of());

            var understanding = new QueryUnderstanding("q", "general", null, null, null, null, null, null, "rule");
            var plan = new RetrievalRoutePlan(
                    List.of(
                            new RouteConfig("lexical_bm25", true, 1.0, 50),
                            new RouteConfig("dense_vector", true, 0.9, 50)
                    ),
                    null, null, null, null, null
            );

            orchestrator.execute(understanding, plan, new float[]{0.1f, 0.2f}, List.of("snap1"));

            verify(denseRetriever).retrieve(any(), any(), anyInt());
        }
    }

    @Nested
    @DisplayName("exception isolation")
    class ExceptionIsolation {
        @Test
        @DisplayName("failing retriever does not crash orchestrator")
        void failingRetrieverIsolated() {
            when(bm25Retriever.retrieve(any(), any(), anyInt()))
                    .thenThrow(new RuntimeException("DB error"));

            var understanding = new QueryUnderstanding("q", "general", null, null, null, null, null, null, "rule");
            var plan = new RetrievalRoutePlan(
                    List.of(new RouteConfig("lexical_bm25", true, 1.0, 50)),
                    null, null, null, null, null
            );

            var result = orchestrator.execute(understanding, plan, null, List.of("snap1"));
            // Should not throw, but trace records the error
            assertThat(result.routeTraces()).hasSize(1);
            assertThat(result.candidates()).isEmpty();
        }
    }

    @Nested
    @DisplayName("unregistered route")
    class UnregisteredRoute {
        @Test
        @DisplayName("unregistered route traced as not_registered")
        void unregisteredTraced() {
            var understanding = new QueryUnderstanding("q", "general", null, null, null, null, null, null, "rule");
            var plan = new RetrievalRoutePlan(
                    List.of(new RouteConfig("unknown_route", true, 1.0, 50)),
                    null, null, null, null, null
            );

            var result = orchestrator.execute(understanding, plan, null, List.of("snap1"));
            assertThat(result.routeTraces()).hasSize(1);
            assertThat(result.routeTraces().get(0).skippedReason()).isEqualTo("not_registered");
        }
    }
}
