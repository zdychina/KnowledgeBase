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

    private static com.coremasterkb.serving.mapper.result.SegmentWithMetaRow seg(String id, String discourseRole) {
        var row = new com.coremasterkb.serving.mapper.result.SegmentWithMetaRow();
        row.setId(id);
        row.setRawText("text-" + id);
        row.setBlockType("paragraph");
        row.setSemanticRole("concept");
        row.setMetadataJson(discourseRole == null ? "{}" : "{\"discourse_role\":\"" + discourseRole + "\"}");
        return row;
    }

    private static com.coremasterkb.serving.mapper.result.SegmentWithMetaRow segWithSection(String id, String sectionTitle) {
        var row = new com.coremasterkb.serving.mapper.result.SegmentWithMetaRow();
        row.setId(id);
        row.setRawText("text-" + id);
        row.setBlockType("paragraph");
        row.setSemanticRole("concept");
        row.setMetadataJson("{}");
        row.setSectionPath("[{\"title\":\"" + sectionTitle + "\",\"level\":1}]");
        return row;
    }

    /** Average 0-based position of seed items whose discourse_role equals {@code role}. */
    private static double avgRank(List<ContextItem> seeds, String role) {
        double sum = 0;
        int n = 0;
        for (int i = 0; i < seeds.size(); i++) {
            if (role.equals(seeds.get(i).metadata().get("discourse_role"))) {
                sum += i;
                n++;
            }
        }
        return n == 0 ? Double.NaN : sum / n;
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
        @DisplayName("nucleus seeds rank ahead of satellite seeds (avg rank lower)")
        void nucleusSeedsRankAheadOfSatellite() {
            var understanding = new QueryUnderstanding("SMF配置", "concept_lookup", null, null, null, null,
                    EvidenceNeed.empty(), null, "rule", null);
            var scope = new ActiveScope("rel", "build", List.of("snap1"), Map.of());
            // expansion off; keep all seeds
            var plan = new RetrievalRoutePlan(null, null, null, null,
                    new AssemblyConfig(false, false, 10, 10, 2, List.of()), null);

            // Highest-scored are satellites; lowest-scored are nuclei — so any
            // nucleus-first ordering must come from discourse role, not score.
            var candidates = List.of(
                    new RetrievalCandidate("u_satA", 0.90, "bm25",
                            Map.of("text", "卫星A", "source_segment_id", "segA"), null),
                    new RetrievalCandidate("u_satC", 0.80, "bm25",
                            Map.of("text", "卫星C", "source_segment_id", "segC"), null),
                    new RetrievalCandidate("u_nucB", 0.50, "bm25",
                            Map.of("text", "核心B", "source_segment_id", "segB"), null),
                    new RetrievalCandidate("u_nucD", 0.40, "bm25",
                            Map.of("text", "核心D", "source_segment_id", "segD"), null));

            when(repo.resolveSegmentsByIds(any(), any())).thenReturn(List.of(
                    seg("segA", "satellite"), seg("segB", "nucleus"),
                    seg("segC", "satellite"), seg("segD", "nucleus")));
            when(repo.getRelationsForSegments(any(), any(), any())).thenReturn(List.of());
            when(repo.getDocumentSources(any(), any())).thenReturn(List.of());

            var pack = assembler.assemble("SMF配置", understanding, scope, candidates, plan);

            var seeds = pack.items().stream().filter(i -> "seed".equals(i.role())).toList();
            assertThat(seeds).hasSize(4);
            // First seed must be a nucleus despite its lower relevance score
            assertThat(seeds.get(0).metadata().get("discourse_role")).isEqualTo("nucleus");

            double nucAvg = avgRank(seeds, "nucleus");
            double satAvg = avgRank(seeds, "satellite");
            assertThat(nucAvg).isLessThan(satAvg);
        }

        @Test
        @DisplayName("tree navigation: in-chapter seed ranks ahead despite lower score")
        void navigatedSectionSeedsRankAhead() {
            var understanding = new QueryUnderstanding("SMF 会话管理", "concept_lookup", null, null, null, null,
                    EvidenceNeed.empty(), null, "rule", null);
            var scope = new ActiveScope("rel", "build", List.of("snap1"), Map.of());
            var plan = new RetrievalRoutePlan(null, null, null, null,
                    new AssemblyConfig(false, false, 10, 10, 2, List.of()), null);

            var candidates = List.of(
                    new RetrievalCandidate("u_out", 0.90, "bm25",
                            Map.of("text", "其他", "source_segment_id", "segOut"), null),
                    new RetrievalCandidate("u_in", 0.50, "bm25",
                            Map.of("text", "会话", "source_segment_id", "segIn"), null));

            when(repo.resolveSegmentsByIds(any(), any())).thenReturn(List.of(
                    segWithSection("segOut", "其他章节"),
                    segWithSection("segIn", "SMF")));
            when(repo.getRelationsForSegments(any(), any(), any())).thenReturn(List.of());
            when(repo.getDocumentSources(any(), any())).thenReturn(List.of());

            var pack = assembler.assemble("SMF 会话管理", understanding, scope, candidates, plan,
                    java.util.Set.of("smf"));

            var seeds = pack.items().stream().filter(i -> "seed".equals(i.role())).toList();
            // In-chapter seed promoted to the top despite its lower relevance score
            assertThat(seeds.get(0).id()).isEqualTo("u_in");
            assertThat(seeds.get(0).metadata().get("in_navigated_section")).isEqualTo(true);
        }

        @Test
        @DisplayName("missing discourse_role leaves seed order unchanged (graceful degradation)")
        void missingDiscourseRoleKeepsOrder() {
            var understanding = new QueryUnderstanding("SMF配置", "concept_lookup", null, null, null, null,
                    EvidenceNeed.empty(), null, "rule", null);
            var scope = new ActiveScope("rel", "build", List.of("snap1"), Map.of());
            var plan = new RetrievalRoutePlan(null, null, null, null,
                    new AssemblyConfig(false, false, 10, 10, 2, List.of()), null);

            var candidates = List.of(
                    new RetrievalCandidate("u1", 0.90, "bm25",
                            Map.of("text", "一", "source_segment_id", "segA"), null),
                    new RetrievalCandidate("u2", 0.50, "bm25",
                            Map.of("text", "二", "source_segment_id", "segB"), null));

            // Segments without discourse_role in metadata_json (pre-feature data)
            when(repo.resolveSegmentsByIds(any(), any())).thenReturn(List.of(
                    seg("segA", null), seg("segB", null)));
            when(repo.getRelationsForSegments(any(), any(), any())).thenReturn(List.of());
            when(repo.getDocumentSources(any(), any())).thenReturn(List.of());

            var pack = assembler.assemble("SMF配置", understanding, scope, candidates, plan);
            var seeds = pack.items().stream().filter(i -> "seed".equals(i.role())).toList();
            // Original (relevance) order preserved: u1 then u2
            assertThat(seeds.get(0).id()).isEqualTo("u1");
            assertThat(seeds.get(1).id()).isEqualTo("u2");
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
}
