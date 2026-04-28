package com.coremasterkb.serving.config;

import com.coremasterkb.serving.application.ContextAssembler;
import com.coremasterkb.serving.application.QueryLogService;
import com.coremasterkb.serving.application.QueryNormalizer;
import com.coremasterkb.serving.application.SearchService;
import com.coremasterkb.serving.client.LlmRuntimeClient;
import com.coremasterkb.serving.mapper.*;
import com.coremasterkb.serving.mapper.ServingQueryLogMapper;
import com.coremasterkb.serving.pipeline.*;
import com.coremasterkb.serving.repository.AssetRepository;
import com.coremasterkb.serving.retrieval.FtsRetriever;
import com.coremasterkb.serving.retrieval.GraphExpander;
import com.coremasterkb.serving.retrieval.Retriever;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.List;

/**
 * Spring @Bean wiring for all serving components.
 * Mappers are injected automatically via @MapperScan on AgentServingApplication.
 */
@Configuration
public class ServingBeans {

    private final ServingProperties properties;

    public ServingBeans(ServingProperties properties) {
        this.properties = properties;
    }

    // -------------------------------------------------------------------------
    // Infrastructure
    // -------------------------------------------------------------------------

    @Bean
    public LlmRuntimeClient llmRuntimeClient() {
        return new LlmRuntimeClient(properties.getLlmService());
    }

    // -------------------------------------------------------------------------
    // Repository + graph
    // -------------------------------------------------------------------------

    @Bean
    public AssetRepository assetRepository(
            AssetPublishReleaseMapper releaseMapper,
            AssetBuildDocumentSnapshotMapper buildSnapshotMapper,
            AssetRawSegmentMapper rawSegmentMapper,
            AssetRawSegmentRelationMapper relationMapper,
            AssetDocumentMapper documentMapper) {
        return new AssetRepository(
                releaseMapper, buildSnapshotMapper,
                rawSegmentMapper, relationMapper, documentMapper);
    }

    @Bean
    public GraphExpander graphExpander(AssetRepository repo) {
        return new GraphExpander(repo);
    }

    // -------------------------------------------------------------------------
    // Retrieval
    // -------------------------------------------------------------------------

    @Bean
    public FtsRetriever ftsRetriever(AssetRetrievalUnitMapper retrievalUnitMapper) {
        return new FtsRetriever(retrievalUnitMapper);
    }

    @Bean
    public RetrieverManager retrieverManager(FtsRetriever ftsRetriever) {
        List<Retriever> retrievers = List.of(ftsRetriever);
        return new RetrieverManager(retrievers);
    }

    // -------------------------------------------------------------------------
    // Pipeline: fusion + reranker
    // -------------------------------------------------------------------------

    @Bean
    public IdentityFusion identityFusion() {
        return new IdentityFusion();
    }

    @Bean
    public RRFFusion rrfFusion() {
        return new RRFFusion();
    }

    @Bean
    public ScoreReranker scoreReranker() {
        return new ScoreReranker();
    }

    // -------------------------------------------------------------------------
    // Pipeline: planner
    // -------------------------------------------------------------------------

    @Bean
    public RulePlannerProvider rulePlannerProvider() {
        return new RulePlannerProvider();
    }

    @Bean
    public QueryPlanner queryPlanner(RulePlannerProvider rulePlannerProvider) {
        return new QueryPlanner(rulePlannerProvider);
    }

    // -------------------------------------------------------------------------
    // Application
    // -------------------------------------------------------------------------

    @Bean
    public QueryNormalizer queryNormalizer(LlmRuntimeClient llmRuntimeClient) {
        LlmRuntimeClient effective = properties.getLlmService().isEnabled()
                ? llmRuntimeClient : null;
        return new QueryNormalizer(effective);
    }

    @Bean
    public ContextAssembler contextAssembler(
            AssetRepository assetRepository, GraphExpander graphExpander) {
        return new ContextAssembler(assetRepository, graphExpander);
    }

    // -------------------------------------------------------------------------
    // Logging (cross-cutting, wired separately from business beans)
    // -------------------------------------------------------------------------

    @Bean
    public QueryLogService queryLogService(ServingQueryLogMapper servingQueryLogMapper) {
        return new QueryLogService(servingQueryLogMapper);
    }

    @Bean
    public SearchService searchService(
            QueryNormalizer normalizer,
            QueryPlanner planner,
            AssetRepository assetRepository,
            RetrieverManager retrieverManager,
            IdentityFusion identityFusion,
            RRFFusion rrfFusion,
            ScoreReranker scoreReranker,
            ContextAssembler contextAssembler) {
        return new SearchService(
                normalizer, planner, assetRepository,
                retrieverManager, identityFusion, rrfFusion,
                scoreReranker, contextAssembler);
    }
}
