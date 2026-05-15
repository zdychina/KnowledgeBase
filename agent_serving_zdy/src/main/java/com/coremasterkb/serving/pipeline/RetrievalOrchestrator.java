package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.FusionConfig;
import com.coremasterkb.serving.domain.OrchestratorResult;
import com.coremasterkb.serving.domain.QueryUnderstanding;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.RetrievalQuery;
import com.coremasterkb.serving.domain.RetrievalRoutePlan;
import com.coremasterkb.serving.domain.RouteConfig;
import com.coremasterkb.serving.domain.RouteTrace;
import com.coremasterkb.serving.domain.ServingConstants;
import com.coremasterkb.serving.domain.SubQuery;
import com.coremasterkb.serving.retrieval.Retriever;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * Orchestrates multi-route retrieval with full query semantics.
 *
 * <p>For each enabled route in the plan, the orchestrator:
 * <ul>
 *   <li>Locates the registered {@link Retriever} by route name</li>
 *   <li>Auto-skips routes that lack required input (e.g. dense_vector without embedding)</li>
 *   <li>Executes retrieval with exception isolation</li>
 *   <li>Normalizes candidate source to the canonical route name</li>
 * </ul>
 *
 * <p>After all routes complete, candidates are fused using the strategy
 * specified in {@link FusionConfig#method()} and traces are returned for observability.</p>
 */
public class RetrievalOrchestrator {

    private final Map<String, Retriever> retrievers;

    public RetrievalOrchestrator(Map<String, Retriever> retrievers) {
        this.retrievers = Objects.requireNonNull(retrievers, "retrievers must not be null");
    }

    /**
     * Execute all enabled routes and return merged candidates with traces.
     *
     * @param understanding   query understanding result
     * @param routePlan       route configuration plan
     * @param queryEmbedding  pre-computed query embedding; may be null
     * @param snapshotIds     snapshot IDs in scope; if empty, returns empty result
     * @return orchestrator result with candidates and route traces
     */
    public OrchestratorResult execute(
            QueryUnderstanding understanding,
            RetrievalRoutePlan routePlan,
            float[] queryEmbedding,
            List<String> snapshotIds) {

        if (snapshotIds == null || snapshotIds.isEmpty()) {
            return OrchestratorResult.empty();
        }

        // 1. Build RetrievalQuery from understanding + embedding
        var retrievalQuery = new RetrievalQuery(
                understanding.originalQuery(),
                understanding.keywords(),
                understanding.entities(),
                queryEmbedding,
                understanding.subQueries().stream().map(SubQuery::text).toList(),
                understanding.intent(),
                understanding.scope()
        );

        // 2. Build route config map (only enabled routes)
        Map<String, RouteConfig> routeConfigMap = new LinkedHashMap<>();
        for (var rc : routePlan.routes()) {
            if (rc.enabled()) {
                routeConfigMap.put(rc.name(), rc);
            }
        }

        // 3. Execute each route
        List<RouteTrace> traces = new ArrayList<>();
        List<RetrievalCandidate> allCandidates = new ArrayList<>();

        for (var entry : routeConfigMap.entrySet()) {
            String routeName = entry.getKey();
            RouteConfig routeCfg = entry.getValue();

            Retriever retriever = retrievers.get(routeName);
            if (retriever == null) {
                traces.add(new RouteTrace(routeName, false, 0, "not_registered", 0));
                continue;
            }

            // Auto-skip dense_vector when no embedding available
            if (ServingConstants.ROUTE_DENSE_VECTOR.equals(routeName)
                    && (queryEmbedding == null || queryEmbedding.length == 0)) {
                traces.add(new RouteTrace(routeName, false, 0, "no_embedding", 0));
                continue;
            }

            // Execute with exception isolation — catch here so one failing route
            // doesn't abort the others; failure is recorded in the trace.
            long start = System.nanoTime();
            List<RetrievalCandidate> candidates;
            try {
                candidates = retriever.retrieve(retrievalQuery, snapshotIds, routeCfg.topK());
            } catch (Exception e) {
                double latencyMs = (System.nanoTime() - start) / 1_000_000.0;
                traces.add(new RouteTrace(routeName, false, 0, e.getMessage(), latencyMs));
                continue;
            }
            double latencyMs = (System.nanoTime() - start) / 1_000_000.0;

            // Normalize source to canonical route name
            List<RetrievalCandidate> annotated = new ArrayList<>();
            for (var c : candidates) {
                if (!routeName.equals(c.source())) {
                    c = c.withSource(routeName);
                }
                annotated.add(c);
            }
            allCandidates.addAll(annotated);
            traces.add(new RouteTrace(routeName, true, annotated.size(), "", latencyMs));
        }

        return new OrchestratorResult(allCandidates, traces);
    }

}
