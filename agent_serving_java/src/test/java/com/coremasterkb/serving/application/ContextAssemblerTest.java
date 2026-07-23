package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.*;
import com.coremasterkb.serving.mapper.result.ExpandedSegmentRow;
import com.coremasterkb.serving.mapper.result.SegmentWithMetaRow;
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
                    EvidenceNeed.empty(), null, "rule", null);
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
                    EvidenceNeed.empty(), null, "rule", null);
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
                    EvidenceNeed.empty(), null, "rule", null);
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
                    null, null, null, null, EvidenceNeed.empty(), null, "rule", null);
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

    @Nested
    @DisplayName("item deduplication")
    class ItemDeduplication {

        /**
         * selectWithMeta LEFT JOINs asset_document_snapshot_links (1:N), so a segment whose
         * snapshot has multiple links comes back as several rows sharing the same id. Those
         * duplicate rows must not become duplicate context items.
         */
        @Test
        @DisplayName("fan-out rows for one segment id yield a single context item")
        void joinFanOutIsDeduped() {
            var understanding = new QueryUnderstanding("业务感知", "concept_lookup", null, null, null, null,
                    EvidenceNeed.empty(), null, "rule", null);
            var scope = new ActiveScope("rel", "build", List.of("snap1"), Map.of());
            var plan = new RetrievalRoutePlan(null, null, null, null,
                    new AssemblyConfig(false, false, 10, 10, 2, List.of()), null);

            // Candidate whose underlying source is seg1.
            var candidate = new RetrievalCandidate("u1", 0.85, "bm25",
                    Map.of("source_segment_id", "seg1", "text", "seed text"), null);

            // Same seg1 returned 3× (one row per snapshot link path) — the JOIN fan-out.
            when(repo.resolveSegmentsByIds(any(), any())).thenReturn(List.of(
                    seg("seg1", "业务感知定义_1.md"),
                    seg("seg1", "业务感知功能描述/业务感知定义_1.md"),
                    seg("seg1", "另一目录/业务感知定义_1.md")));
            when(repo.getRelationsForSegments(any(), any(), any())).thenReturn(List.of());
            when(repo.getDocumentSources(any(), any())).thenReturn(List.of());

            var pack = assembler.assemble("业务感知", understanding, scope, List.of(candidate), plan);

            long seg1Count = pack.items().stream()
                    .filter(i -> "seg1".equals(i.id()))
                    .count();
            assertThat(seg1Count).isEqualTo(1);
            assertThat(pack.items().stream().map(ContextItem::id).distinct().count())
                    .isEqualTo(pack.items().size());
        }

        /**
         * A segment reached both as a direct source (role=context) and via graph expansion
         * (role=support) must appear once; the first occurrence (context) wins.
         */
        @Test
        @DisplayName("segment reached via both source and expansion is deduped, context wins")
        void sourceAndExpansionOverlapIsDeduped() {
            var understanding = new QueryUnderstanding("业务感知", "concept_lookup", null, null, null, null,
                    EvidenceNeed.empty(), null, "rule", null);
            var scope = new ActiveScope("rel", "build", List.of("snap1"), Map.of());
            var plan = new RetrievalRoutePlan(null, null, null, null,
                    new AssemblyConfig(true, true, 10, 10, 2, List.of("elaborates")), null);

            var candidate = new RetrievalCandidate("u1", 0.85, "bm25",
                    Map.of("source_segment_id", "seg1", "text", "seed text"), null);

            when(repo.resolveSegmentsByIds(any(), any()))
                    .thenReturn(List.of(seg("seg1", "业务感知定义_1.md")));
            // Expansion returns the very same seg1 (cross-list duplicate).
            when(graphExpander.expand(any(), anyInt(), any(), anyInt(), any()))
                    .thenReturn(List.of(new ExpandedSegmentRow(
                            seg("seg1", "业务感知定义_1.md"), 1, "seg1", "elaborates")));
            when(repo.getRelationsForSegments(any(), any(), any())).thenReturn(List.of());
            when(repo.getDocumentSources(any(), any())).thenReturn(List.of());

            var pack = assembler.assemble("业务感知", understanding, scope, List.of(candidate), plan);

            var seg1Items = pack.items().stream()
                    .filter(i -> "seg1".equals(i.id()))
                    .toList();
            assertThat(seg1Items).hasSize(1);
            assertThat(seg1Items.get(0).role()).isEqualTo("context");
        }

        private SegmentWithMetaRow seg(String id, String relativePath) {
            var row = new SegmentWithMetaRow();
            row.setId(id);
            row.setDocumentSnapshotId("snap1");
            row.setRawText("业务感知是指对用户数据报文进行解析。");
            row.setBlockType("paragraph");
            row.setSemanticRole("definition");
            row.setSnapshotTitle("业务感知定义");
            row.setDocumentId("doc1");
            row.setRelativePath(relativePath);
            return row;
        }
    }
}
