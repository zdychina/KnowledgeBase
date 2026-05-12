package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.*;
import com.coremasterkb.serving.domainpack.DomainPackReader;
import com.coremasterkb.serving.domainpack.ServingDomainProfile;
import com.coremasterkb.serving.infrastructure.EmbeddingClient;
import com.coremasterkb.serving.observability.TraceCollector;
import com.coremasterkb.serving.pipeline.*;
import com.coremasterkb.serving.rerank.RerankPipeline;
import com.coremasterkb.serving.rerank.RerankPipeline.RerankResult;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

@DisplayName("SearchService")
class SearchServiceTest {

    private QueryUnderstandingEngine quEngine;
    private RetrievalRouter router;
    private RetrievalOrchestrator orchestrator;
    private RerankPipeline rerankPipeline;
    private ContextAssembler assembler;
    private DomainPackReader domainPackReader;
    private EmbeddingClient embeddingClient;
    private SearchService searchService;

    @BeforeEach
    void setUp() {
        quEngine = mock(QueryUnderstandingEngine.class);
        router = mock(RetrievalRouter.class);
        orchestrator = mock(RetrievalOrchestrator.class);
        rerankPipeline = mock(RerankPipeline.class);
        assembler = mock(ContextAssembler.class);
        domainPackReader = mock(DomainPackReader.class);
        embeddingClient = mock(EmbeddingClient.class);

        searchService = new SearchService(
                quEngine, router, orchestrator, rerankPipeline,
                assembler, domainPackReader, embeddingClient);
    }

    @Nested
    @DisplayName("full pipeline orchestration")
    class FullPipeline {
        @Test
        @DisplayName("all pipeline stages called in order")
        void allStagesCalled() {
            var understanding = new QueryUnderstanding("SMF配置", "concept_lookup",
                    List.of(), List.of(), Map.of(), List.of("SMF"),
                    EvidenceNeed.empty(), List.of(), "rule");
            var routePlan = new RetrievalRoutePlan(
                    List.of(new RouteConfig("lexical_bm25", true, 1.0, 50)),
                    Map.of(), new FusionConfig("identity", 60),
                    new RerankConfig("score", "score"),
                    AssemblyConfig.defaults(), ExpansionConfig.defaults());
            var orchResult = OrchestratorResult.empty();
            var rerankResult = new RerankResult(List.of(), List.of());
            var expectedPack = new ContextPack(null, List.of(), List.of(), List.of(),
                    List.of(), List.of(), List.of(), Map.of());

            when(domainPackReader.getProfile(anyString())).thenReturn(null);
            when(quEngine.understand(anyString(), any())).thenReturn(understanding);
            when(router.route(any(), any())).thenReturn(routePlan);
            when(orchestrator.execute(any(), any(), any(), any())).thenReturn(orchResult);
            when(rerankPipeline.rerank(any(), any(), any())).thenReturn(rerankResult);
            when(assembler.assemble(anyString(), any(), any(), any(), any())).thenReturn(expectedPack);

            var request = new SearchRequest("SMF配置", Map.of(), List.of(), false,
                    "cloud_core_network", "evidence");

            // SearchService needs an asset repo for scope resolution
            var assetRepo = mock(com.coremasterkb.serving.repository.AssetRepository.class);
            when(assetRepo.resolveActiveScope(anyString()))
                    .thenReturn(new ActiveScope("rel1", "b1", List.of("snap1"), Map.of()));
            searchService.withAssetRepository(assetRepo);

            var result = searchService.search(request);

            assertThat(result).isNotNull();
            verify(quEngine).understand("SMF配置", null);
            verify(router).route(understanding, null);
            verify(orchestrator).execute(eq(understanding), eq(routePlan), any(), eq(List.of("snap1")));
            verify(rerankPipeline).rerank(any(), eq(routePlan), eq(understanding));
            verify(assembler).assemble(eq("SMF配置"), eq(understanding), any(), any(), eq(routePlan));
        }

        @Test
        @DisplayName("debug flag populates debug map in result")
        void debugFlagPopulatesDebugMap() {
            var understanding = new QueryUnderstanding("test", "general",
                    List.of(), List.of(), Map.of(), List.of(),
                    EvidenceNeed.empty(), List.of(), "rule");
            var routePlan = new RetrievalRoutePlan(
                    List.of(new RouteConfig("lexical_bm25", true, 1.0, 50)),
                    Map.of(), new FusionConfig("identity", 60),
                    new RerankConfig("score", "score"),
                    AssemblyConfig.defaults(), ExpansionConfig.defaults());

            when(domainPackReader.getProfile(anyString())).thenReturn(null);
            when(quEngine.understand(anyString(), any())).thenReturn(understanding);
            when(router.route(any(), any())).thenReturn(routePlan);
            when(orchestrator.execute(any(), any(), any(), any())).thenReturn(OrchestratorResult.empty());
            when(rerankPipeline.rerank(any(), any(), any())).thenReturn(new RerankResult(List.of(), List.of()));
            when(assembler.assemble(anyString(), any(), any(), any(), any()))
                    .thenReturn(new ContextPack(null, List.of(), List.of(), List.of(), List.of(), List.of(), List.of(), Map.of()));

            var assetRepo = mock(com.coremasterkb.serving.repository.AssetRepository.class);
            when(assetRepo.resolveActiveScope(anyString()))
                    .thenReturn(new ActiveScope("rel1", "b1", List.of("snap1"), Map.of()));
            searchService.withAssetRepository(assetRepo);

            var request = new SearchRequest("test", Map.of(), List.of(), true,
                    "cloud_core_network", "evidence");
            var result = searchService.search(request);

            assertThat(result.debug()).containsKey("understanding");
            assertThat(result.debug()).containsKey("trace");
            assertThat(result.debug()).containsKey("fusion_method");
        }

        @Test
        @DisplayName("no asset repo throws IllegalStateException")
        void noAssetRepoThrows() {
            var understanding = new QueryUnderstanding("test", "general",
                    List.of(), List.of(), Map.of(), List.of(),
                    EvidenceNeed.empty(), List.of(), "rule");
            var routePlan = new RetrievalRoutePlan(
                    List.of(new RouteConfig("lexical_bm25", true, 1.0, 50)),
                    Map.of(), new FusionConfig("identity", 60),
                    new RerankConfig("score", "score"),
                    AssemblyConfig.defaults(), ExpansionConfig.defaults());

            when(domainPackReader.getProfile(anyString())).thenReturn(null);
            when(quEngine.understand(anyString(), any())).thenReturn(understanding);
            when(router.route(any(), any())).thenReturn(routePlan);

            var request = new SearchRequest("test", Map.of(), List.of(), false,
                    "cloud_core_network", "evidence");

            assertThatThrownBy(() -> searchService.search(request))
                    .isInstanceOf(IllegalStateException.class)
                    .hasMessageContaining("AssetRepository not configured");
        }
    }
}
