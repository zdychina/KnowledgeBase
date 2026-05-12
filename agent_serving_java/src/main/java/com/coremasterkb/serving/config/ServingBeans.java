package com.coremasterkb.serving.config;

import com.coremasterkb.serving.application.SearchService;
import com.coremasterkb.serving.domainpack.DomainPackReader;
import com.coremasterkb.serving.infrastructure.EmbeddingClient;
import com.coremasterkb.serving.infrastructure.LlmClient;
import com.coremasterkb.serving.infrastructure.ZhipuClient;
import com.coremasterkb.serving.mapper.AssetRawSegmentMapper;
import com.coremasterkb.serving.mapper.AssetRawSegmentRelationMapper;
import com.coremasterkb.serving.mapper.AssetRetrievalEmbeddingMapper;
import com.coremasterkb.serving.mapper.AssetRetrievalUnitMapper;
import com.coremasterkb.serving.pipeline.RetrievalOrchestrator;
import com.coremasterkb.serving.rerank.*;
import com.coremasterkb.serving.retrieval.DenseVectorRetriever;
import com.coremasterkb.serving.retrieval.EntityExactRetriever;
import com.coremasterkb.serving.retrieval.FtsRetriever;
import com.coremasterkb.serving.retrieval.GraphExpander;
import com.coremasterkb.serving.retrieval.Retriever;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestTemplate;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Explicit wiring for plain-Java components that are not annotated with
 * {@code @Component}/{@code @Service}/{@code @Repository}.
 *
 * <p>Components already picked up by component scanning (QueryUnderstandingEngine,
 * RetrievalRouter, ContextAssembler, SearchService, DomainPackReader,
 * QueryLogService, QueryLogAspect, AssetRepository) are NOT declared here.</p>
 */
@Configuration
@EnableConfigurationProperties(ServingProperties.class)
public class ServingBeans {

    private static final Logger log = LoggerFactory.getLogger(ServingBeans.class);

    // -------------------------------------------------------------------------
    // Infrastructure clients
    // -------------------------------------------------------------------------

    @Bean
    public RestTemplate restTemplate() {
        return new RestTemplate();
    }

    @Bean
    public LlmClient llmClient(RestTemplate restTemplate, ServingProperties properties) {
        LlmClient client = new LlmClient(restTemplate, properties.llm().baseUrl(), properties.llm().apiKey());
        try {
            client.ensureTemplates();
        } catch (Exception e) {
            log.warn("Template registration failed (non-fatal): {}", e.getMessage());
        }
        return client;
    }

    @Bean
    public ZhipuClient zhipuClient(ServingProperties properties) {
        return new ZhipuClient(
                properties.zhipu().apiKey(),
                properties.zhipu().baseUrl(),
                properties.zhipu().rerankModel()
        );
    }

    @Bean
    public EmbeddingClient embeddingClient(LlmClient llmClient, ServingProperties properties) {
        return new EmbeddingClient(llmClient, properties.embedding().model(), properties.embedding().dimensions());
    }

    // -------------------------------------------------------------------------
    // Retrieval layer
    // -------------------------------------------------------------------------

    @Bean
    public FtsRetriever ftsRetriever(AssetRetrievalUnitMapper retrievalUnitMapper) {
        return new FtsRetriever(retrievalUnitMapper);
    }

    @Bean
    public DenseVectorRetriever denseVectorRetriever(AssetRetrievalEmbeddingMapper embeddingMapper) {
        return new DenseVectorRetriever(embeddingMapper, 5000);
    }

    @Bean
    public EntityExactRetriever entityExactRetriever(AssetRetrievalUnitMapper retrievalUnitMapper) {
        return new EntityExactRetriever(retrievalUnitMapper);
    }

    @Bean
    public GraphExpander graphExpander(
            AssetRawSegmentRelationMapper relationMapper,
            AssetRawSegmentMapper segmentMapper) {
        return new GraphExpander(relationMapper, segmentMapper);
    }

    @Bean
    public RetrievalOrchestrator retrievalOrchestrator(
            FtsRetriever ftsRetriever,
            DenseVectorRetriever denseVectorRetriever,
            EntityExactRetriever entityExactRetriever) {
        Map<String, Retriever> retrievers = new LinkedHashMap<>();
        retrievers.put("lexical_bm25", ftsRetriever);
        retrievers.put("dense_vector", denseVectorRetriever);
        retrievers.put("entity_exact", entityExactRetriever);
        return new RetrievalOrchestrator(retrievers);
    }

    // -------------------------------------------------------------------------
    // Rerank layer
    // -------------------------------------------------------------------------

    @Bean
    public ScoreReranker scoreReranker() {
        return new ScoreReranker();
    }

    @Bean
    public ZhipuModelReranker zhipuModelReranker(ZhipuClient zhipuClient) {
        return new ZhipuModelReranker(zhipuClient);
    }

    @Bean
    public LlmReranker llmReranker(LlmClient llmClient) {
        return new LlmReranker(llmClient);
    }

    @Bean
    public RerankPipeline rerankPipeline(
            ZhipuModelReranker zhipuModelReranker,
            LlmReranker llmReranker,
            ScoreReranker scoreReranker) {
        return new RerankPipeline(zhipuModelReranker, llmReranker, scoreReranker);
    }

    // -------------------------------------------------------------------------
    // SearchService asset repository injection
    // -------------------------------------------------------------------------

    /**
     * Wire the AssetRepository into SearchService via its withAssetRepository() method.
     * SearchService is auto-detected by component scanning, so we use a BeanPostProcessor
     * approach via an initializer bean.
     */
    @Bean
    public SearchService searchServiceInitializer(SearchService searchService,
                                                   com.coremasterkb.serving.repository.AssetRepository assetRepository) {
        return searchService.withAssetRepository(assetRepository);
    }
}
