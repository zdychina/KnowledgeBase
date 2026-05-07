package com.coremasterkb.serving.config;

import com.coremasterkb.serving.application.ContextAssembler;
import com.coremasterkb.serving.application.QueryLogService;
import com.coremasterkb.serving.application.QueryNormalizer;
import com.coremasterkb.serving.application.SearchService;
import com.coremasterkb.serving.client.LlmRuntimeClient;
import com.coremasterkb.serving.client.ZhipuClient;
import com.coremasterkb.serving.mapper.*;
import com.coremasterkb.serving.pipeline.*;
import com.coremasterkb.serving.repository.AssetRepository;
import com.coremasterkb.serving.retrieval.DenseVectorRetriever;
import com.coremasterkb.serving.retrieval.EntityExactRetriever;
import com.coremasterkb.serving.retrieval.FtsRetriever;
import com.coremasterkb.serving.retrieval.GraphExpander;
import com.coremasterkb.serving.retrieval.Retriever;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.List;

/**
 * Spring @Bean wiring for all serving components.
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

    @Bean
    public ZhipuClient zhipuClient() {
        return new ZhipuClient(properties.getZhipu());
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
            AssetDocumentMapper documentMapper,
            AssetRetrievalEmbeddingMapper embeddingMapper) {
        return new AssetRepository(
                releaseMapper, buildSnapshotMapper,
                rawSegmentMapper, relationMapper, documentMapper, embeddingMapper);
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
    public EntityExactRetriever entityExactRetriever(AssetRetrievalUnitMapper retrievalUnitMapper) {
        return new EntityExactRetriever(retrievalUnitMapper);
    }

    @Bean
    public DenseVectorRetriever denseVectorRetriever(
            ZhipuClient zhipuClient,
            AssetRetrievalEmbeddingMapper embeddingMapper) {
        ServingProperties.DenseVector cfg = properties.getDenseVector();
        return new DenseVectorRetriever(zhipuClient, embeddingMapper, cfg.getTopK(), cfg.getMaxLoad());
    }

    @Bean
    public RetrieverManager retrieverManager(
            FtsRetriever ftsRetriever,
            EntityExactRetriever entityExactRetriever,
            DenseVectorRetriever denseVectorRetriever) {
        List<Retriever> retrievers = List.of(ftsRetriever, entityExactRetriever, denseVectorRetriever);
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
    public WeightedRRFFusion weightedRRFFusion() {
        return new WeightedRRFFusion();
    }

    @Bean
    public ScoreReranker scoreReranker() {
        ServingProperties.Reranker cfg = properties.getReranker();
        return new ScoreReranker(
                cfg.getLowValueBlockPenalty(),
                cfg.getBoostSemanticRole(),
                cfg.getBoostBlockType(),
                cfg.getBoostScopeMatch(),
                cfg.getBoostEntityMatch());
    }

    @Bean
    public ZhipuModelReranker zhipuModelReranker(ZhipuClient zhipuClient) {
        return new ZhipuModelReranker(zhipuClient);
    }

    // -------------------------------------------------------------------------
    // Pipeline: planner
    // -------------------------------------------------------------------------

    @Bean
    public RulePlannerProvider rulePlannerProvider() {
        ServingProperties.Retrieval cfg = properties.getRetrieval();
        return new RulePlannerProvider(cfg.getRrfK(), cfg.getRetrieverWeights());
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
        ServingProperties.Domain domain = properties.getDomain();
        return new QueryNormalizer(effective, domain.getProducts(), domain.getNetworkElements());
    }

    @Bean
    public ContextAssembler contextAssembler(
            AssetRepository assetRepository, GraphExpander graphExpander) {
        return new ContextAssembler(assetRepository, graphExpander,
                properties.getAssembler().getLowConfidenceThreshold());
    }

    // -------------------------------------------------------------------------
    // Logging
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
            WeightedRRFFusion weightedRRFFusion,
            ScoreReranker scoreReranker,
            ZhipuModelReranker zhipuModelReranker,
            ContextAssembler contextAssembler) {
        return new SearchService(
                normalizer, planner, assetRepository,
                retrieverManager, identityFusion, rrfFusion,
                weightedRRFFusion, scoreReranker, zhipuModelReranker,
                contextAssembler);
    }
}
