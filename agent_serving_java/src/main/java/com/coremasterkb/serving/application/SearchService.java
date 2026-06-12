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
import com.coremasterkb.serving.observability.SearchMetrics;
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
    private final MultiQueryExpander multiQueryExpander;
    private final SemanticCacheService semanticCache;
    private final SearchMetrics metrics;
    private final TreeNavigator treeNavigator;
    private final String defaultDomain;
    // Virtual-thread-per-task executor: no pool state to manage, no shutdown required.
    // Each CompletableFuture.supplyAsync spawns a new virtual thread that is cleaned up by the JVM.
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
            MultiQueryExpander multiQueryExpander,
            SemanticCacheService semanticCache,
            SearchMetrics metrics,
            TreeNavigator treeNavigator,
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
        this.multiQueryExpander = multiQueryExpander;
        this.semanticCache = semanticCache;
        this.metrics = metrics;
        this.treeNavigator = treeNavigator;
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

        // 1. Resolve domain first so all downstream components see it
        String effectiveDomain = (request.domain() != null && !request.domain().isBlank())
                ? request.domain() : defaultDomain;
        String channel = (request.channel() != null && !request.channel().isBlank())
                ? request.channel()
                : domainRegistry.getDefaultChannel(effectiveDomain);

        // Validate DB reachable before touching the routing DataSource
        // (throws domain_database_unavailable if the pool cannot connect)
        domainPoolManager.getDataSource(effectiveDomain);

        // All DB operations on this thread now route to the domain's pool
        DomainContext.set(effectiveDomain);
        // Propagate domain to LLM client BEFORE any parallel calls
        llmClient.setKnowledgeDomain(effectiveDomain);

        // Variables declared before try so they're accessible in debug section after finally
        QueryUnderstanding understanding = null;
        RetrievalRoutePlan routePlan = null;
        ActiveScope scope = null;
        List<RetrievalCandidate> ranked = List.of();
        ContextPack pack = null;
        float[] queryEmbedding = null;
        List<RouteTrace> debugRouteTraces = List.of();
        Set<String> navigatedSections = Set.of();

        long pipelineStartMs = System.currentTimeMillis();

        try {

        // 2. Load Domain Profile
        ServingDomainProfile profile = domainPackReader.getProfile(effectiveDomain);

        // 3. Query Understanding + Embedding + Multi-Query Expansion — all in parallel
        //    Embedding is started optimistically — result is only used if dense route is enabled.
        //    Multi-query expansion only needs the raw query, so it can start alongside QU.
        //    NOTE: Virtual threads cannot inherit ThreadLocal from the parent thread.
        //    We must explicitly set knowledge_domain in each async lambda.
        final String threadDomain = effectiveDomain;

        trace.startStage("query_understanding");
        CompletableFuture<QueryUnderstanding> understandingFuture = CompletableFuture.supplyAsync(
                () -> {
                    llmClient.setKnowledgeDomain(threadDomain);
                    try {
                        return quEngine.understand(request.query(), profile);
                    } finally {
                        llmClient.clearKnowledgeDomain();
                    }
                }, pipelineExecutor);

        CompletableFuture<float[]> embeddingFuture = embeddingClient.isConfigured()
                ? CompletableFuture.supplyAsync(() -> {
            llmClient.setKnowledgeDomain(threadDomain);
            try {
                return embeddingClient.embed(request.query());
            } catch (Exception e) {
                log.warn("Query embedding failed: {}", e.getMessage());
                return null;
            } finally {
                llmClient.clearKnowledgeDomain();
            }
        }, pipelineExecutor)
                : CompletableFuture.completedFuture(null);

        CompletableFuture<List<String>> multiQueryFuture = CompletableFuture.supplyAsync(() -> {
            llmClient.setKnowledgeDomain(threadDomain);
            try {
                return multiQueryExpander.expand(request.query());
            } finally {
                llmClient.clearKnowledgeDomain();
            }
        }, pipelineExecutor);

        understanding = understandingFuture.join();
        log.info("[search] query_understanding done: {}ms", System.currentTimeMillis() - pipelineStartMs);
        trace.endStage("query_understanding",
                "intent=" + understanding.intent()
                        + ", entities=" + understanding.entities().size()
                        + ", source=" + understanding.source());
        log.info("[QU] intent={}, complexity={}, entities={}, source={}",
                understanding.intent(), understanding.queryComplexity(),
                understanding.entities().size(), understanding.source());
        metrics.recordIntent(understanding.intent());

        // 4. Retrieval Router
        trace.startStage("retrieval_router");
        routePlan = router.route(understanding, profile);
        trace.endStage("retrieval_router",
                "routes=" + routePlan.routes().size()
                        + ", fusion=" + routePlan.fusion().method());

        String dbEnvVar = domainRegistry.findEntry(effectiveDomain)
                .map(e -> e.databaseUrlEnv() != null ? e.databaseUrlEnv() : "default(shared)")
                .orElse("default(shared)");
        log.info("[search] routing domain={} channel={} db={}", effectiveDomain, channel, dbEnvVar);

        trace.startStage("resolve_scope");
        try {
            scope = resolveActiveScope(effectiveDomain, channel);
        } catch (IllegalArgumentException e) {
            trace.endStage("resolve_scope", "error=" + e.getMessage());
            throw e;
        }
        trace.endStage("resolve_scope", "snapshots=" + scope.snapshotIds().size());
        log.info("[search] scope resolved: {}ms", System.currentTimeMillis() - pipelineStartMs);

        // 3.4. Tree navigation: infer relevant chapters for query entities
        trace.startStage("tree_navigation");
        TreeNavigation nav = treeNavigator.inferSections(understanding.entities(), scope.snapshotIds());
        if (nav == null) nav = TreeNavigation.empty();
        navigatedSections = nav.softSections();
        List<String> sectionHardFilter = nav.hardFilter() ? nav.hardPrefixes() : List.of();
        trace.endStage("tree_navigation",
                "soft=" + navigatedSections.size() + ", hard=" + sectionHardFilter.size());
        log.info("[search] tree_navigation done: {}ms", System.currentTimeMillis() - pipelineStartMs);

        // 3.5. Multi-Query Expansion (already started in parallel with QU)
        trace.startStage("multi_query_expand");
        List<String> queryVariants = multiQueryFuture.join();
        trace.endStage("multi_query_expand", "variants=" + queryVariants.size());
        log.info("[search] multi_query_expand done ({} variants): {}ms", queryVariants.size(), System.currentTimeMillis() - pipelineStartMs);

        // 5. Collect pre-computed embedding (started in parallel with understanding)
        boolean denseEnabled = routePlan.routes().stream()
                .anyMatch(r -> "dense_vector".equals(r.name()) && r.enabled());
        if (denseEnabled && embeddingClient.isConfigured()) {
            trace.startStage("embedding");
            queryEmbedding = embeddingFuture.join();
            trace.endStage("embedding",
                    "dim=" + (queryEmbedding != null ? queryEmbedding.length : 0));
        } else {
            queryEmbedding = embeddingFuture.join();
        }
        log.info("[search] embedding done: {}ms", System.currentTimeMillis() - pipelineStartMs);

        // 5.5. Semantic cache lookup
        trace.startStage("semantic_cache");
        ContextPack cachedPack = semanticCache.lookup(effectiveDomain, scope.releaseId(), queryEmbedding);
        if (cachedPack != null) {
            trace.endStage("semantic_cache", "hit=true");
            return cachedPack;
        }
        trace.endStage("semantic_cache", "hit=false");

        // 6. Retrieve for each variant — parallel execution
        trace.startStage("retrieve");
        List<RetrievalCandidate> rawCandidates = Collections.synchronizedList(new ArrayList<>());
        List<RouteTrace> allRouteTraces = Collections.synchronizedList(new ArrayList<>());
        List<CompletableFuture<Void>> retrievalFutures = new ArrayList<>();

        // Capture effectively-final values for lambda use
        final QueryUnderstanding finalUnderstanding = understanding;
        final float[] finalQueryEmbedding = queryEmbedding;
        final boolean finalDenseEnabled = denseEnabled;
        final RetrievalRoutePlan finalRoutePlan = routePlan;
        final List<String> finalSnapshotIds = scope.snapshotIds();
        final List<String> finalSectionHardFilter = sectionHardFilter;

        for (String variant : queryVariants) {
            QueryUnderstanding varUnderstanding = variant.equals(request.query())
                    ? finalUnderstanding
                    : buildVariantUnderstanding(finalUnderstanding, variant);
            boolean isOriginal = variant.equals(request.query());

            CompletableFuture<Void> f = CompletableFuture.runAsync(() -> {
                DomainContext.set(threadDomain);
                llmClient.setKnowledgeDomain(threadDomain);
                try {
                    // Reuse original query embedding for all variants — avoids 800ms per-variant
                    // embedding call with negligible accuracy loss for dense retrieval.
                    float[] variantEmbedding = finalQueryEmbedding;
                    OrchestratorResult varResult = orchestrator.execute(
                            varUnderstanding, finalRoutePlan, variantEmbedding,
                            finalSnapshotIds, finalSectionHardFilter);
                    rawCandidates.addAll(varResult.candidates());
                    allRouteTraces.addAll(varResult.routeTraces());
                } finally {
                    llmClient.clearKnowledgeDomain();
                    DomainContext.clear();
                }
            }, pipelineExecutor);
            retrievalFutures.add(f);
        }

        // 6b. Sub-query decomposition (cap at 4) — also parallel
        for (SubQuery subQuery : finalUnderstanding.subQueries().stream().limit(4).toList()) {
            QueryUnderstanding subUnderstanding = buildSubQueryUnderstanding(finalUnderstanding, subQuery);
            CompletableFuture<Void> f = CompletableFuture.runAsync(() -> {
                DomainContext.set(threadDomain);
                llmClient.setKnowledgeDomain(threadDomain);
                try {
                    OrchestratorResult subResult = orchestrator.execute(
                            subUnderstanding, finalRoutePlan, finalQueryEmbedding,
                            finalSnapshotIds, finalSectionHardFilter);
                    rawCandidates.addAll(subResult.candidates());
                    allRouteTraces.addAll(subResult.routeTraces());
                } finally {
                    llmClient.clearKnowledgeDomain();
                    DomainContext.clear();
                }
            }, pipelineExecutor);
            retrievalFutures.add(f);
        }

        // Wait for all variant + sub-query retrievals to complete
        CompletableFuture.allOf(retrievalFutures.toArray(CompletableFuture[]::new)).join();

        trace.endStage("retrieve",
                "candidates=" + rawCandidates.size() + ", variants=" + queryVariants.size());
        log.info("[search] retrieve done ({} candidates): {}ms", rawCandidates.size(), System.currentTimeMillis() - pipelineStartMs);

        debugRouteTraces = List.copyOf(allRouteTraces);

        // Observability: per-route candidate counts
        for (RouteTrace rt : allRouteTraces) {
            if (rt.attempted()) {
                metrics.recordRouteCandidates(rt.name(), rt.candidateCount());
            }
        }

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
        log.info("[search] fusion done ({} fused): {}ms", fused.size(), System.currentTimeMillis() - pipelineStartMs);

        // 8. Rerank (cascading: model -> LLM -> score)
        trace.startStage("rerank");
        long rerankStartNanos = System.nanoTime();
        var rerankResult = rerankPipeline.rerank(fused, routePlan, understanding);
        metrics.recordRerankDuration((System.nanoTime() - rerankStartNanos) / 1_000_000.0);
        ranked = rerankResult.candidates();
        metrics.recordRerankFallback(resolveWinningRerankMethod(rerankResult.traces()));
        trace.endStage("rerank", "ranked=" + ranked.size());
        log.info("[search] rerank done ({} ranked): {}ms", ranked.size(), System.currentTimeMillis() - pipelineStartMs);

        // 9. Assemble ContextPack
        trace.startStage("assembly");
        pack = assembler.assemble(
                request.query(), understanding, scope, ranked, routePlan, navigatedSections);
        trace.endStage("assembly", "items=" + pack.items().size());

        // Observability: empty-scope no-result
        boolean noSeedResult = pack.items().stream().noneMatch(i -> "seed".equals(i.role()));
        if (noSeedResult && understanding.scope().isEmpty()) {
            metrics.recordScopeEmpty();
        }

        // 9.5. Store result in semantic cache (best-effort)
        semanticCache.store(effectiveDomain, scope.releaseId(), request.query(), queryEmbedding, pack);

        } finally {
            DomainContext.clear();
            llmClient.clearKnowledgeDomain();
        }

        // Unreachable if an exception was thrown inside try, so pack is guaranteed non-null here
        ContextPack result = pack;
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
            if (!debugRouteTraces.isEmpty()) {
                debugInfo.put("route_traces", routeTracesToList(debugRouteTraces));
            }

            result = new ContextPack(
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

        log.info("[search] OK items={}", result.items().size());
        return result;
    }

    // =========================================================================
    // Scope resolution
    // =========================================================================

    private ActiveScope resolveActiveScope(String domain, String channel) {
        return assetRepository.resolveActiveScope(domain, channel);
    }

    private static String resolveWinningRerankMethod(List<RerankTraceStep> traces) {
        if (traces != null) {
            for (int i = traces.size() - 1; i >= 0; i--) {
                if (traces.get(i).succeeded()) {
                    return traces.get(i).provider();
                }
            }
        }
        return "score";
    }

    // =========================================================================
    // Multi-query helpers
    // =========================================================================

    private static QueryUnderstanding buildVariantUnderstanding(
            QueryUnderstanding original, String variantQuery) {
        return new QueryUnderstanding(
                variantQuery, original.intent(), original.subQueries(),
                original.entities(), original.scope(), original.keywords(),
                original.evidenceNeed(), original.ambiguities(), original.source(),
                original.queryComplexity()
        );
    }

    private static QueryUnderstanding buildSubQueryUnderstanding(
            QueryUnderstanding parent, SubQuery subQuery) {
        String intent = !"general".equals(subQuery.intent())
                ? subQuery.intent() : parent.intent();
        List<EntityRef> entities = !subQuery.entities().isEmpty()
                ? subQuery.entities() : parent.entities();
        return new QueryUnderstanding(
                subQuery.text(), intent, List.of(), entities,
                parent.scope(), parent.keywords(), parent.evidenceNeed(),
                parent.ambiguities(), parent.source(), parent.queryComplexity()
        );
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
