package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.*;
import com.coremasterkb.serving.domainpack.DomainContext;
import com.coremasterkb.serving.domainpack.DomainPackReader;
import com.coremasterkb.serving.domainpack.DomainPoolManager;
import com.coremasterkb.serving.domainpack.DomainRegistry;
import com.coremasterkb.serving.config.ServingProperties;
import com.coremasterkb.serving.domainpack.ServingDomainProfile;
import com.coremasterkb.serving.infrastructure.EmbeddingClient;
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
    private final MultiQueryExpander multiQueryExpander;
    private final SemanticCacheService semanticCache;
    private final SessionStore sessionStore;
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
            MultiQueryExpander multiQueryExpander,
            SemanticCacheService semanticCache,
            SessionStore sessionStore,
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
        this.multiQueryExpander = multiQueryExpander;
        this.semanticCache = semanticCache;
        this.sessionStore = sessionStore;
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

        // Session: load prior queries for multi-turn context enrichment
        String sessionId = request.sessionId();
        List<String> priorQueries = (sessionId != null && !sessionId.isBlank())
                ? sessionStore.getPriorQueries(sessionId)
                : List.of();

        // Build query string for QU: prepend session history to help with coreference resolution
        String quQuery = request.query();
        if (!priorQueries.isEmpty()) {
            StringBuilder sb = new StringBuilder("以下是用户的问题历史：\n");
            for (String pq : priorQueries) {
                sb.append("- ").append(pq).append("\n");
            }
            sb.append("当前问题：").append(request.query());
            quQuery = sb.toString();
        }

        // 1. Load Domain Profile
        ServingDomainProfile profile = domainPackReader.getProfile(request.domain());

        // Start HyDE embedding of original query optimistically — runs in parallel with QU.
        // The result is reused when step 5 collects all variant embeddings.
        CompletableFuture<float[]> originalEmbFuture = embeddingClient.isConfigured()
                ? CompletableFuture.supplyAsync(() -> {
                    try {
                        return embeddingClient.embedHyDE(request.query());
                    } catch (Exception e) {
                        log.warn("Original query embedding failed: {}", e.getMessage());
                        return null;
                    }
                }, pipelineExecutor)
                : CompletableFuture.completedFuture(null);

        // 2. Query Understanding (LLM-first, rule fallback)
        // complexityHint from request overrides auto-derivation when present
        trace.startStage("query_understanding");
        QueryUnderstanding understanding = quEngine.understand(quQuery, profile, request.complexityHint());
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
        List<RouteTrace> allRouteTraces = new ArrayList<>();
        ContextPack pack = null;
        float[] queryEmbedding = null;
        try {
            trace.startStage("resolve_scope");
            try {
                scope = resolveActiveScope(effectiveDomain, channel);
            } catch (IllegalArgumentException e) {
                trace.endStage("resolve_scope", "error=" + e.getMessage());
                throw e;
            }
            trace.endStage("resolve_scope", "snapshots=" + scope.snapshotIds().size());

            // 3.5. Multi-Query Expansion: original + up to 2 LLM variants
            trace.startStage("multi_query_expand");
            List<String> queryVariants = multiQueryExpander.expand(request.query());
            trace.endStage("multi_query_expand", "variants=" + queryVariants.size());

            // 5. Generate embeddings in parallel for all variants and sub-queries (HyDE per text).
            // The original query future was already launched before QU; other texts are started here.
            // Total latency ≈ slowest single HyDE call, not sum of all calls.
            boolean denseEnabled = routePlan.routes().stream()
                    .anyMatch(r -> "dense_vector".equals(r.name()) && r.enabled());
            Map<String, float[]> variantEmbeddings = new java.util.LinkedHashMap<>();
            if (denseEnabled && embeddingClient.isConfigured()) {
                trace.startStage("embedding");

                // Collect all texts to embed: variants first, then sub-queries (deduped)
                Set<String> allTexts = new LinkedHashSet<>(queryVariants);
                for (var sq : understanding.subQueries()) allTexts.add(sq.text());

                // Launch one CompletableFuture per text; reuse the pre-computed future for the original query
                Map<String, CompletableFuture<float[]>> futures = new LinkedHashMap<>();
                for (String text : allTexts) {
                    if (text.equals(request.query())) {
                        futures.put(text, originalEmbFuture);
                    } else {
                        futures.put(text, CompletableFuture.supplyAsync(() -> {
                            try {
                                return embeddingClient.embedHyDE(text);
                            } catch (Exception e) {
                                log.warn("Embedding failed for variant: {}", e.getMessage());
                                return null;
                            }
                        }, pipelineExecutor));
                    }
                }

                // Join all futures (parallel — each future may already be complete)
                for (var entry : futures.entrySet()) {
                    float[] emb = entry.getValue().join();
                    if (emb != null) variantEmbeddings.put(entry.getKey(), emb);
                }

                queryEmbedding = variantEmbeddings.get(request.query());
                trace.endStage("embedding",
                        "texts=" + variantEmbeddings.size()
                        + ", dim=" + (queryEmbedding != null ? queryEmbedding.length : 0));
            }

            // 5.5. Semantic cache lookup (after embedding, before heavy retrieval)
            trace.startStage("semantic_cache");
            ContextPack cachedPack = semanticCache.lookup(effectiveDomain, queryEmbedding);
            if (cachedPack != null) {
                trace.endStage("semantic_cache", "hit=true");
                log.info("[search] semantic cache hit, skipping pipeline");
                return cachedPack;
            }
            trace.endStage("semantic_cache", "hit=false");

            // 6. Retrieve for each variant and sub-query, merge candidates
            trace.startStage("retrieve");
            List<RetrievalCandidate> rawCandidates = new java.util.ArrayList<>();

            // 6a. Multi-query variants
            for (String variant : queryVariants) {
                float[] varEmb = variantEmbeddings.get(variant);
                QueryUnderstanding varUnderstanding = variant.equals(request.query())
                        ? understanding
                        : buildVariantUnderstanding(understanding, variant);
                OrchestratorResult varResult = orchestrator.execute(
                        varUnderstanding, routePlan, varEmb, scope.snapshotIds());
                rawCandidates.addAll(varResult.candidates());
                allRouteTraces.addAll(varResult.routeTraces());
            }

            // 6b. Query decomposition: retrieve for each LLM-identified sub-query
            for (com.coremasterkb.serving.domain.SubQuery subQuery : understanding.subQueries()) {
                QueryUnderstanding subUnderstanding = buildSubQueryUnderstanding(understanding, subQuery);
                float[] subEmb = variantEmbeddings.get(subQuery.text());
                OrchestratorResult subResult = orchestrator.execute(
                        subUnderstanding, routePlan, subEmb, scope.snapshotIds());
                rawCandidates.addAll(subResult.candidates());
                allRouteTraces.addAll(subResult.routeTraces());
            }

            trace.endStage("retrieve",
                    "candidates=" + rawCandidates.size()
                    + ", variants=" + queryVariants.size()
                    + ", sub_queries=" + understanding.subQueries().size());

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

            // 9.5. Store result in semantic cache (best-effort, non-blocking)
            semanticCache.store(effectiveDomain, request.query(), queryEmbedding, pack);

            // 9.6. Record turn in session for multi-turn context accumulation
            if (sessionId != null && !sessionId.isBlank()) {
                try {
                    sessionStore.recordTurn(sessionId, request.query());
                } catch (Exception e) {
                    log.warn("Session recordTurn failed (non-fatal): {}", e.getMessage());
                }
            }

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
            if (!allRouteTraces.isEmpty()) {
                debugInfo.put("route_traces", routeTracesToList(allRouteTraces));
            }
            if (sessionId != null && !sessionId.isBlank()) {
                debugInfo.put("session_id", sessionId);
                debugInfo.put("session_prior_queries", priorQueries);
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
    // Multi-query helpers
    // =========================================================================

    /**
     * Build a lightweight QueryUnderstanding for a variant query, reusing the
     * original's intent/entities/scope while replacing only the originalQuery field.
     */
    private static QueryUnderstanding buildVariantUnderstanding(
            QueryUnderstanding original, String variantQuery) {
        return new QueryUnderstanding(
                variantQuery,
                original.intent(),
                original.subQueries(),
                original.entities(),
                original.scope(),
                original.keywords(),
                original.evidenceNeed(),
                original.ambiguities(),
                original.source(),
                original.queryComplexity()
        );
    }

    /**
     * Build a QueryUnderstanding for a decomposed sub-query.
     * Uses the sub-query's own intent/entities when available; falls back to the parent's.
     */
    private static QueryUnderstanding buildSubQueryUnderstanding(
            QueryUnderstanding parent, com.coremasterkb.serving.domain.SubQuery subQuery) {
        String intent = !"general".equals(subQuery.intent())
                ? subQuery.intent() : parent.intent();
        List<com.coremasterkb.serving.domain.EntityRef> entities = !subQuery.entities().isEmpty()
                ? subQuery.entities() : parent.entities();
        return new QueryUnderstanding(
                subQuery.text(),
                intent,
                List.of(),   // no recursive decomposition
                entities,
                parent.scope(),
                parent.keywords(),
                parent.evidenceNeed(),
                parent.ambiguities(),
                parent.source(),
                parent.queryComplexity()
        );
    }

    // =========================================================================
    // Debug info helpers
    // =========================================================================

    private static Map<String, Object> understandingToMap(QueryUnderstanding u) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("original_query", u.originalQuery());
        map.put("intent", u.intent());
        map.put("complexity", u.queryComplexity());
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
}
