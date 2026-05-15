package com.coremasterkb.serving.config;

import com.coremasterkb.serving.application.SearchService;
import com.coremasterkb.serving.domainpack.DomainPackReader;
import com.coremasterkb.serving.domainpack.DomainPoolManager;
import com.coremasterkb.serving.domainpack.DomainRoutingDataSource;
import com.coremasterkb.serving.infrastructure.EmbeddingClient;
import com.coremasterkb.serving.infrastructure.LlmClient;
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
import com.zaxxer.hikari.HikariDataSource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.jdbc.DataSourceProperties;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

import javax.sql.DataSource;
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
    // DataSource configuration (DataSourceAutoConfiguration is excluded)
    // -------------------------------------------------------------------------

    /**
     * Binds spring.datasource.* connection properties (url, username, password, driver).
     * DataSourceAutoConfiguration is excluded so we own the full DataSource lifecycle.
     */
    @Bean
    @ConfigurationProperties("spring.datasource")
    public DataSourceProperties dataSourceProperties() {
        return new DataSourceProperties();
    }

    /**
     * Default HikariCP pool — used as the fallback when no domain-specific DB is configured.
     * Pool settings (minimum-idle, maximum-pool-size, connection-timeout) come from
     * spring.datasource.hikari.* via @ConfigurationProperties.
     */
    @Bean("defaultDataSource")
    @ConfigurationProperties("spring.datasource.hikari")
    public HikariDataSource defaultDataSource(DataSourceProperties dataSourceProperties) {
        return dataSourceProperties.initializeDataSourceBuilder()
                .type(HikariDataSource.class)
                .build();
    }

    /**
     * Primary DataSource that routes every JDBC connection to the pool owned by the
     * current request's domain. Falls back to {@code defaultDataSource} when no domain
     * is set on the thread (health checks, startup probes, test setup).
     *
     * <p>Named "dataSource" as an alias so that Spring Boot autoconfiguration classes
     * (JdbcTemplateAutoConfiguration, DataSourceTransactionManagerAutoConfiguration)
     * that look up {@code @Qualifier("dataSource")} find this routing bean rather than
     * failing with NoSuchBeanDefinitionException.
     */
    @Bean({"dataSource", "domainRoutingDataSource"})
    @Primary
    public DataSource domainRoutingDataSource(
            DomainPoolManager poolManager,
            @Qualifier("defaultDataSource") DataSource defaultDataSource) {
        return new DomainRoutingDataSource(poolManager, defaultDataSource);
    }

    // -------------------------------------------------------------------------
    // Infrastructure clients
    // -------------------------------------------------------------------------

    @Bean
    public RestTemplate restTemplate() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5_000);
        factory.setReadTimeout(60_000);
        return new RestTemplate(factory);
    }

    @Bean
    public LlmClient llmClient(RestTemplate restTemplate, ServingProperties properties) {
        LlmClient client = new LlmClient(restTemplate, properties.llm().baseUrl());
        try {
            client.ensureTemplates();
        } catch (Exception e) {
            log.warn("Template registration failed (non-fatal): {}", e.getMessage());
        }
        return client;
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
        return new DenseVectorRetriever(embeddingMapper);
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
    public LlmReranker llmReranker(LlmClient llmClient) {
        return new LlmReranker(llmClient);
    }

    @Bean
    public LlmServiceReranker llmServiceReranker(LlmClient llmClient, ServingProperties properties) {
        return new LlmServiceReranker(llmClient, properties.rerank().model());
    }

    @Bean
    public RerankPipeline rerankPipeline(
            LlmServiceReranker llmServiceReranker,
            LlmReranker llmReranker,
            ScoreReranker scoreReranker) {
        return new RerankPipeline(llmServiceReranker, llmReranker, scoreReranker);
    }

}
