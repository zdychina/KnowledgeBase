package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.*;
import com.coremasterkb.serving.repository.AssetRepository;
import com.coremasterkb.serving.retrieval.GraphExpander;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@DisplayName("ContextAssembler")
class ContextAssemblerTest {

    private AssetRepository repo;
    private GraphExpander graphExpander;
    private ContextAssembler assembler;

    @BeforeEach
    void setUp() {
        repo = mock(AssetRepository.class);
        graphExpander = mock(GraphExpander.class);
        assembler = new ContextAssembler(repo, graphExpander);
    }

    @Nested
    @DisplayName("empty candidates")
    class EmptyCandidates {
        @Test
        @DisplayName("empty candidates produces no_result issue")
        void emptyProducesNoResultIssue() {
            var understanding = new QueryUnderstanding("xyzzy123", "general", null, null, null, null,
                    EvidenceNeed.empty(), null, "rule");
            var scope = new ActiveScope("rel", "build", List.of("snap1"), Map.of());
            var plan = new RetrievalRoutePlan(null, null, null, null, null, null);

            when(repo.resolveSegmentsByIds(any(), any())).thenReturn(List.of());
            when(repo.getDocumentSources(any(), any())).thenReturn(List.of());

            var pack = assembler.assemble("xyzzy123", understanding, scope, List.of(), plan);
            assertThat(pack.issues()).isNotEmpty();
            assertThat(pack.issues().get(0).type()).isEqualTo("no_result");
            assertThat(pack.items()).isEmpty();
        }
    }

    @Nested
    @DisplayName("low score candidates")
    class LowScoreCandidates {
        @Test
        @DisplayName("all low scores produces low_confidence issue")
        void lowScoreProducesLowConfidenceIssue() {
            var understanding = new QueryUnderstanding("模糊查询", "general", null, null, null, null,
                    EvidenceNeed.empty(), null, "rule");
            var scope = new ActiveScope("rel", "build", List.of("snap1"), Map.of());
            var plan = new RetrievalRoutePlan(null, null, null, null,
                    new AssemblyConfig(false, false, 10, 10, 2, List.of()), null);

            var candidate = new RetrievalCandidate("u1", 0.05, "bm25",
                    Map.of("text", "some text"), null);

            when(repo.resolveSegmentsByIds(any(), any())).thenReturn(List.of());
            when(repo.getRelationsForSegments(any(), any(), any())).thenReturn(List.of());
            when(repo.getDocumentSources(any(), any())).thenReturn(List.of());

            var pack = assembler.assemble("模糊查询", understanding, scope, List.of(candidate), plan);
            assertThat(pack.issues()).isNotEmpty();
            assertThat(pack.issues().get(0).type()).isEqualTo("low_confidence");
        }
    }

    @Nested
    @DisplayName("normal candidates")
    class NormalCandidates {
        @Test
        @DisplayName("candidates produce seed items")
        void candidatesProduceSeedItems() {
            var understanding = new QueryUnderstanding("SMF配置", "concept_lookup", null, null, null, null,
                    EvidenceNeed.empty(), null, "rule");
            var scope = new ActiveScope("rel", "build", List.of("snap1"), Map.of());
            var plan = new RetrievalRoutePlan(null, null, null, null,
                    new AssemblyConfig(false, false, 10, 10, 2, List.of()), null);

            var candidate = new RetrievalCandidate("u1", 0.85, "bm25",
                    Map.of("text", "SMF配置相关内容"), null);

            when(repo.resolveSegmentsByIds(any(), any())).thenReturn(List.of());
            when(repo.getRelationsForSegments(any(), any(), any())).thenReturn(List.of());
            when(repo.getDocumentSources(any(), any())).thenReturn(List.of());

            var pack = assembler.assemble("SMF配置", understanding, scope, List.of(candidate), plan);
            assertThat(pack.items()).isNotEmpty();
            assertThat(pack.items().get(0).role()).isEqualTo("seed");
            assertThat(pack.items().get(0).score()).isEqualTo(0.85);
            assertThat(pack.issues()).isEmpty();
        }

        @Test
        @DisplayName("contextQuery populated from understanding")
        void contextQueryPopulated() {
            var understanding = new QueryUnderstanding("SMF配置", "concept_lookup",
                    null, null, null, null, EvidenceNeed.empty(), null, "rule");
            var scope = new ActiveScope("rel", "build", List.of("snap1"), Map.of());
            var plan = new RetrievalRoutePlan(null, null, null, null,
                    new AssemblyConfig(false, false, 10, 10, 2, List.of()), null);

            var candidate = new RetrievalCandidate("u1", 0.85, "bm25", Map.of(), null);

            when(repo.resolveSegmentsByIds(any(), any())).thenReturn(List.of());
            when(repo.getRelationsForSegments(any(), any(), any())).thenReturn(List.of());
            when(repo.getDocumentSources(any(), any())).thenReturn(List.of());

            var pack = assembler.assemble("SMF配置", understanding, scope, List.of(candidate), plan);
            assertThat(pack.query()).isNotNull();
            assertThat(pack.query().original()).isEqualTo("SMF配置");
            assertThat(pack.query().intent()).isEqualTo("concept_lookup");
        }
    }
}
