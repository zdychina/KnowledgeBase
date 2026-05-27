package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.*;
import com.coremasterkb.serving.config.ServingProperties;
import com.coremasterkb.serving.domainpack.DomainContext;
import com.coremasterkb.serving.domainpack.DomainPackReader;
import com.coremasterkb.serving.domainpack.DomainPoolManager;
import com.coremasterkb.serving.domainpack.DomainRegistry;
import com.coremasterkb.serving.domainpack.ServingDomainProfile;
import com.coremasterkb.serving.infrastructure.EmbeddingClient;
import com.coremasterkb.serving.infrastructure.LlmClient;
import com.coremasterkb.serving.observability.TraceCollector;
import com.coremasterkb.serving.pipeline.*;
import com.coremasterkb.serving.rerank.RerankPipeline;
import com.coremasterkb.serving.repository.AssetRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

/**
 * Main search orchestrator wiring all components together.
 *
 * <p>Pipeline: understand &rarr; route &rarr; resolve scope &rarr;
 * retrieve &rarr; fuse &rarr; rerank &rarr; assemble.
 * Each stage is traced via {@link TraceCollector}.
 * Matches Python's search() endpoint behavior.
 */
@Service
public class SearchService {

    private static final Logger log = LoggerFactory.getLogger(SearchService.class);

    private final QueryUnderstandingEngine quEngine;
    private final RetrievalRouter router;
    private final RetrievalOrchestrator orchestrator;
    private final RerankPipeline rerankPipeline;
    private final ContextAssembler assembler;
    private final DomainPackReader domainPackReader;
    private final DomainRegistry domainRegistry;
    private final DomainPoolManager domainPoolManager;
    private final EmbeddingClient embeddingClient;
    private final AssetRepository assetRepository;
    private final LlmClient llmClient;
    private final String defaultDomain;
    private final Executor pipelineExecutor = Executors.newVirtualThreadPerTaskExecutor();

    public SearchService(
            QueryUnderstandingEngine quEngine,
            RetrievalRouter router,
            RetrievalOrchestrator orchestrator,
            RerankPipeline rerankPipeline,
            ContextAssembler assembler,
            DomainPackReader domainPackReader,
            DomainRegistry domainRegistry,
            DomainPoolManager domainPoolManager,
            EmbeddingClient embeddingClient,
            AssetRepository assetRepository,
            LlmClient llmClient,
            ServingProperties properties) {
        this.quEngine = quEngine;
        this.router = router;
        this.orchestrator = orchestrator;
        this.rerankPipeline = rerankPipeline;
        this.assembler = assembler;
        this.domainPackReader = domainPackReader;
        this.domainRegistry = domainRegistry;
        this.domainPoolManager = domainPoolManager;
        this.embeddingClient = embeddingClient;
        this.assetRepository = assetRepository;
        this.llmClient = llmClient;
        this.defaultDomain = properties.defaultDomain();
        if (!embeddingClient.isConfigured()) {
            log.info("Embedding client not configured (LLM_SERVICE_URL blank) — dense retrieval disabled");
        }
    }

    /**
     * Execute the full search pipeline.
     *
     * @param request search request containing query, domain, scope, etc.
     * @return assembled context pack with results
     */
    public ContextPack search(SearchRequest request) {
        if (request.query() == null || request.query().isBlank()) {
            throw new IllegalArgumentException("query_required");
        }

        TraceCollector trace = new TraceCollector();

        // 1. Load Domain Profile
        ServingDomainProfile profile = domainPackReader.getProfile(request.domain());

        // 2. Query Understanding + Embedding in parallel
        //    Embedding is started optimistically — result is only used if dense route is enabled.
        trace.startStage("query_understanding");
        CompletableFuture<QueryUnderstanding> understandingFuture = CompletableFuture.supplyAsync(
                () -> quEngine.understand(request.query(), profile), pipelineExecutor);
        CompletableFuture<float[]> embeddingFuture = embeddingClient.isConfigured()
                ? CompletableFuture.supplyAsync(() -> {
            try {
                return embeddingClient.embed(request.query());
            } catch (Exception e) {
                log.warn("Query embedding failed: {}", e.getMessage());
                return null;
            }
        }, pipelineExecutor)
                : CompletableFuture.completedFuture(null);

        QueryUnderstanding understanding = understandingFuture.join();
        trace.endStage("query_understanding",
                "intent=" + understanding.intent()
                        + ", entities=" + understanding.entities().size()
                        + ", source=" + understanding.source());

        // 3. Retrieval Router
        trace.startStage("retrieval_router");
        RetrievalRoutePlan routePlan = router.route(understanding, profile);
        trace.endStage("retrieval_router",
                "routes=" + routePlan.routes().size()
                        + ", fusion=" + routePlan.fusion().method());

        // 4. Resolve domain and channel; validate DB availability
        String effectiveDomain = (request.domain() != null && !request.domain().isBlank())
                ? request.domain() : defaultDomain;
        String channel = (request.channel() != null && !request.channel().isBlank())
                ? request.channel()
                : domainRegistry.getDefaultChannel(effectiveDomain);

        // Propagate domain to LLM client for billing/audit
        llmClient.setKnowledgeDomain(effectiveDomain);

        // Validate DB reachable before touching the routing DataSource
        // (throws domain_database_unavailable if the pool cannot connect)
        domainPoolManager.getDataSource(effectiveDomain);

        String dbEnvVar = domainRegistry.findEntry(effectiveDomain)
                .map(e -> e.databaseUrlEnv() != null ? e.databaseUrlEnv() : "default(shared)")
                .orElse("default(shared)");
        log.info("[search] routing domain={} channel={} db={}", effectiveDomain, channel, dbEnvVar);

        // All DB operations on this thread now route to the domain's pool
        DomainContext.set(effectiveDomain);
        ActiveScope scope = null;
        List<RetrievalCandidate> ranked = List.of();
        ContextPack pack = null;
        float[] queryEmbedding = null;
        OrchestratorResult orchResult = null;
        try {
            trace.startStage("resolve_scope");
            try {
                scope = resolveActiveScope(effectiveDomain, channel);
            } catch (IllegalArgumentException e) {
                trace.endStage("resolve_scope", "error=" + e.getMessage());
                throw e;
            }
            trace.endStage("resolve_scope", "snapshots=" + scope.snapshotIds().size());

            // 5. Collect pre-computed embedding (started in parallel with understanding)
            boolean denseEnabled = routePlan.routes().stream()
                    .anyMatch(r -> "dense_vector".equals(r.name()) && r.enabled());
            if (denseEnabled && embeddingClient.isConfigured()) {
                trace.startStage("embedding");
                queryEmbedding = embeddingFuture.join();
                trace.endStage("embedding",
                        "dim=" + (queryEmbedding != null ? queryEmbedding.length : 0));
            } else {
                queryEmbedding = embeddingFuture.join(); // consume future to avoid wasted thread
            }

            // 6. Retrieve from all configured routes
            trace.startStage("retrieve");
            orchResult = orchestrator.execute(
                    understanding, routePlan, queryEmbedding, scope.snapshotIds());
            List<RetrievalCandidate> rawCandidates = orchResult.candidates();
            trace.endStage("retrieve", "candidates=" + rawCandidates.size());

            // 7. Fuse
            trace.startStage("fusion");
            FusionStrategy fusion = switch (routePlan.fusion().method()) {
                case "weighted_rrf" -> new WeightedRRFFusion();
                case "rrf" -> new RRFFusion();
                default -> new IdentityFusion();
            };
            List<RetrievalCandidate> fused = fusion.fuse(rawCandidates, routePlan);
            trace.endStage("fusion",
                    "fused=" + fused.size() + ", method=" + routePlan.fusion().method());

            // 8. Rerank (cascading: model -> LLM -> score)
            trace.startStage("rerank");
            var rerankResult = rerankPipeline.rerank(fused, routePlan, understanding);
            ranked = rerankResult.candidates();
            trace.endStage("rerank", "ranked=" + ranked.size());

            // 9. Assemble ContextPack
            trace.startStage("assembly");
            pack = assembler.assemble(
                    request.query(), understanding, scope, ranked, routePlan);
            trace.endStage("assembly", "items=" + pack.items().size());

        } finally {
            DomainContext.clear();
        }

        // 10. Build debug info if requested
        if (request.debug()) {
            Trace fullTrace = trace.buildTrace();
            Map<String, Object> debugInfo = new LinkedHashMap<>();
            debugInfo.put("understanding", understandingToMap(understanding));
            debugInfo.put("route_plan", routePlanToMap(routePlan));
            debugInfo.put("domain_context", domainContextToMap(effectiveDomain, channel, scope));
            debugInfo.put("trace", traceToMap(fullTrace));
            debugInfo.put("candidate_count", ranked.size());
            debugInfo.put("fusion_method", routePlan.fusion().method());
            debugInfo.put("query_embedding_dim", queryEmbedding != null ? queryEmbedding.length : 0);
            if (orchResult != null) {
                debugInfo.put("route_traces", routeTracesToList(orchResult.routeTraces()));
            }

            // Return new pack with debug info added
            return new ContextPack(
                    pack.query(),
                    pack.items(),
                    pack.relations(),
                    pack.sources(),
                    pack.evidenceGroups(),
                    pack.issues(),
                    pack.suggestions(),
                    debugInfo
            );
        }

        log.info("[search] OK items={}", pack.items().size());
        return pack;
    }

    // =========================================================================
    // Scope resolution
    // =========================================================================

    private ActiveScope resolveActiveScope(String domain, String channel) {
        return assetRepository.resolveActiveScope(domain, channel);
    }

    // =========================================================================
    // Debug info helpers
    // =========================================================================

    private static Map<String, Object> understandingToMap(QueryUnderstanding u) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("original_query", u.originalQuery());
        map.put("intent", u.intent());
        map.put("source", u.source());
        map.put("keywords", u.keywords());
        map.put("entities_count", u.entities().size());
        return map;
    }

    private static Map<String, Object> routePlanToMap(RetrievalRoutePlan p) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("routes_count", p.routes().size());
        map.put("fusion_method", p.fusion().method());
        map.put("rerank_method", p.rerank().method());
        return map;
    }

    private Map<String, Object> domainContextToMap(String domain, String channel, ActiveScope scope) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("domain", domain);
        map.put("channel", channel);
        domainRegistry.findEntry(domain).ifPresentOrElse(
                entry -> {
                    map.put("database", entry.databaseUrlEnv() != null ? entry.databaseUrlEnv() : "n/a");
                    map.put("scenario_pack", entry.scenarioPack());
                },
                () -> {
                    map.put("database", "n/a");
                    map.put("scenario_pack", domain);
                }
        );
        map.put("release_id", scope.releaseId());
        map.put("build_id", scope.buildId());
        map.put("snapshot_count", scope.snapshotIds().size());
        return map;
    }

    private static Map<String, Object> traceToMap(Trace t) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("request_id", t.requestId());
        map.put("total_duration_ms", t.totalDurationMs());
        List<Map<String, Object>> stages = new ArrayList<>();
        for (var s : t.stages()) {
            Map<String, Object> stageMap = new LinkedHashMap<>();
            stageMap.put("name", s.name());
            stageMap.put("duration_ms", s.durationMs());
            stageMap.put("summary", s.outputSummary());
            stages.add(stageMap);
        }
        map.put("stages", stages);
        return map;
    }

    private static List<Map<String, Object>> routeTracesToList(List<RouteTrace> traces) {
        List<Map<String, Object>> list = new ArrayList<>();
        for (var t : traces) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("route", t.name());
            m.put("attempted", t.attempted());
            m.put("candidate_count", t.candidateCount());
            m.put("skipped_reason", t.skippedReason());
            m.put("latency_ms", Math.round(t.latencyMs() * 100.0) / 100.0);
            list.add(m);
        }
        return list;
    }
}
