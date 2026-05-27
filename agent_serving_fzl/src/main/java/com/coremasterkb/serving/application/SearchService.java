package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.*;
import com.coremasterkb.serving.domainpack.DomainPackReader;
import com.coremasterkb.serving.domainpack.ServingDomainProfile;
import com.coremasterkb.serving.infrastructure.EmbeddingClient;
import com.coremasterkb.serving.observability.TraceCollector;
import com.coremasterkb.serving.pipeline.*;
import com.coremasterkb.serving.rerank.RerankPipeline;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.*;

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
    private final EmbeddingClient embeddingClient;

    public SearchService(
            QueryUnderstandingEngine quEngine,
            RetrievalRouter router,
            RetrievalOrchestrator orchestrator,
            RerankPipeline rerankPipeline,
            ContextAssembler assembler,
            DomainPackReader domainPackReader,
            EmbeddingClient embeddingClient) {
        this.quEngine = quEngine;
        this.router = router;
        this.orchestrator = orchestrator;
        this.rerankPipeline = rerankPipeline;
        this.assembler = assembler;
        this.domainPackReader = domainPackReader;
        this.embeddingClient = embeddingClient;
    }

    /**
     * Execute the full search pipeline.
     *
     * @param request search request containing query, domain, scope, etc.
     * @return assembled context pack with results
     */
    public ContextPack search(SearchRequest request) {
        TraceCollector trace = new TraceCollector();

        // 1. Load Domain Profile
        ServingDomainProfile profile = domainPackReader.getProfile(request.domain());

        // 2. Query Understanding (LLM-first, rule fallback)
        trace.startStage("query_understanding");
        QueryUnderstanding understanding = quEngine.understand(request.query(), profile);
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

        // 4. Resolve Active Scope
        trace.startStage("resolve_scope");
        ActiveScope scope;
        try {
            // Resolve using the domain from the request
            String domain = request.domain() != null && !request.domain().isBlank()
                    ? request.domain() : "default";
            scope = resolveActiveScope(domain);
        } catch (IllegalArgumentException e) {
            trace.endStage("resolve_scope", "error=" + e.getMessage());
            throw e;
        }
        trace.endStage("resolve_scope", "snapshots=" + scope.snapshotIds().size());

        // 5. Generate query embedding (if dense route enabled)
        float[] queryEmbedding = null;
        boolean denseEnabled = routePlan.routes().stream()
                .anyMatch(r -> "dense_vector".equals(r.name()) && r.enabled());
        if (denseEnabled && embeddingClient != null) {
            trace.startStage("embedding");
            try {
                queryEmbedding = embeddingClient.embed(request.query());
            } catch (Exception e) {
                log.warn("Query embedding failed: {}", e.getMessage());
            }
            trace.endStage("embedding",
                    "dim=" + (queryEmbedding != null ? queryEmbedding.length : 0));
        }

        // 6. Retrieve from all configured routes
        trace.startStage("retrieve");
        OrchestratorResult orchResult = orchestrator.execute(
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
        List<RetrievalCandidate> ranked = rerankResult.candidates();
        trace.endStage("rerank", "ranked=" + ranked.size());

        // 9. Assemble ContextPack
        trace.startStage("assembly");
        ContextPack pack = assembler.assemble(
                request.query(), understanding, scope, ranked, routePlan);
        trace.endStage("assembly", "items=" + pack.items().size());

        // 10. Build debug info if requested
        if (request.debug()) {
            Trace fullTrace = trace.buildTrace();
            Map<String, Object> debugInfo = new LinkedHashMap<>();
            debugInfo.put("understanding", understandingToMap(understanding));
            debugInfo.put("route_plan", routePlanToMap(routePlan));
            debugInfo.put("scope", scopeToMap(scope));
            debugInfo.put("trace", traceToMap(fullTrace));
            debugInfo.put("candidate_count", ranked.size());
            debugInfo.put("fusion_method", routePlan.fusion().method());
            debugInfo.put("query_embedding_dim", queryEmbedding != null ? queryEmbedding.length : 0);

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
    // Scope resolution (delegates to repository — needs domain)
    // =========================================================================

    // This will be injected via AssetRepository in the actual wiring.
    // For now, we use a separate method that can be overridden or wired.
    private com.coremasterkb.serving.repository.AssetRepository assetRepository;

    public SearchService withAssetRepository(com.coremasterkb.serving.repository.AssetRepository repo) {
        this.assetRepository = repo;
        return this;
    }

    private ActiveScope resolveActiveScope(String domain) {
        if (assetRepository != null) {
            return assetRepository.resolveActiveScope(domain);
        }
        throw new IllegalStateException("AssetRepository not configured — call withAssetRepository() first");
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

    private static Map<String, Object> scopeToMap(ActiveScope s) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("release_id", s.releaseId());
        map.put("snapshot_count", s.snapshotIds().size());
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
}
