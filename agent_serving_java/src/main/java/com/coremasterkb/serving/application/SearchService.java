package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.*;
import com.coremasterkb.serving.pipeline.*;
import com.coremasterkb.serving.repository.AssetRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.*;

/**
 * Orchestrates the full retrieval pipeline.
 *
 * Pipeline:
 *   normalize → plan → resolveScope → retrieve → fuse → rerank → assemble
 *
 * Reranker cascade: ZhipuModelReranker (if available) → ScoreReranker (fallback)
 * Fusion selection: weighted_rrf | rrf | identity
 */
@Service
public class SearchService {

    private static final Logger log = LoggerFactory.getLogger(SearchService.class);
    private static final String DEFAULT_CHANNEL = "default";

    private final QueryNormalizer normalizer;
    private final QueryPlanner planner;
    private final AssetRepository assetRepo;
    private final RetrieverManager retrieverManager;
    private final IdentityFusion identityFusion;
    private final RRFFusion rrfFusion;
    private final WeightedRRFFusion weightedRRFFusion;
    private final ScoreReranker scoreReranker;
    private final ZhipuModelReranker zhipuReranker;
    private final ContextAssembler assembler;

    public SearchService(
            QueryNormalizer normalizer,
            QueryPlanner planner,
            AssetRepository assetRepo,
            RetrieverManager retrieverManager,
            IdentityFusion identityFusion,
            RRFFusion rrfFusion,
            WeightedRRFFusion weightedRRFFusion,
            ScoreReranker scoreReranker,
            ZhipuModelReranker zhipuReranker,
            ContextAssembler assembler
    ) {
        this.normalizer       = normalizer;
        this.planner          = planner;
        this.assetRepo        = assetRepo;
        this.retrieverManager = retrieverManager;
        this.identityFusion   = identityFusion;
        this.rrfFusion        = rrfFusion;
        this.weightedRRFFusion = weightedRRFFusion;
        this.scoreReranker    = scoreReranker;
        this.zhipuReranker    = zhipuReranker;
        this.assembler        = assembler;
    }

    /**
     * @throws IllegalArgumentException("no_active_release")        → 503
     * @throws IllegalArgumentException("multiple_active_releases") → 500
     */
    public ContextPack search(SearchRequest request) {
        String rawQuery = request.query();

        // Step 1: Normalize
        NormalizedQuery normalized = normalizer.normalize(rawQuery);

        // Step 2: Plan
        QueryPlan plan = planner.plan(normalized, request.scope(), request.entities());

        // Step 3: Resolve active scope
        ActiveScope scope = assetRepo.resolveActiveScope(DEFAULT_CHANNEL);

        // Step 4: Retrieve (all enabled retrievers)
        List<RetrievalCandidate> candidates =
                retrieverManager.retrieve(plan, scope.snapshotIds());

        // Step 5: Fuse
        FusionStrategy fusion = selectFusion(plan.retrieverConfig().fusionMethod());
        List<RetrievalCandidate> fused = fusion.fuse(candidates, plan);

        // Step 6: Rerank — cascade: ZhipuModel → Score
        String rerankerUsed = "score";
        List<RetrievalCandidate> reranked = zhipuReranker.rerank(fused, plan);
        if (reranked != null) {
            rerankerUsed = "zhipu_model";
        } else {
            reranked = scoreReranker.rerank(fused, plan);
        }

        // Step 7: Assemble
        ContextPack pack = assembler.assemble(rawQuery, normalized, plan, scope, reranked);

        // Step 8: Attach debug info if requested
        if (request.debug()) {
            Map<String, Object> debug = new LinkedHashMap<>();
            debug.put("intent",            plan.intent());
            debug.put("keywords",          plan.keywords());
            debug.put("scope_constraints", plan.scopeConstraints());
            debug.put("fusion_method",     plan.retrieverConfig().fusionMethod());
            debug.put("retriever_weights", plan.retrieverConfig().retrieverWeights());
            debug.put("reranker_used",     rerankerUsed);
            debug.put("candidate_count",   reranked.size());
            debug.put("snapshot_ids",      scope.snapshotIds());
            debug.put("release_id",        scope.releaseId());
            debug.put("build_id",          scope.buildId());

            pack = new ContextPack(
                    pack.query(), pack.items(), pack.relations(),
                    pack.sources(), pack.issues(), pack.suggestions(), debug);
        }

        return pack;
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    private FusionStrategy selectFusion(String method) {
        if (method == null) return identityFusion;
        return switch (method.toLowerCase()) {
            case "weighted_rrf" -> weightedRRFFusion;
            case "rrf"          -> rrfFusion;
            default             -> identityFusion;
        };
    }
}
