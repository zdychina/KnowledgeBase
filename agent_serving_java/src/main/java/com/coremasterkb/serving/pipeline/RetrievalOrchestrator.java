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
import com.coremasterkb.serving.domainpack.DomainContext;
import com.coremasterkb.serving.retrieval.Retriever;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.Executor;

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
 * <p>When an {@link Executor} is provided, all routes execute in parallel using
 * {@link CompletableFuture} with {@link DomainContext} propagation. Otherwise,
 * routes run sequentially (for tests or single-route setups).</p>
 */
public class RetrievalOrchestrator {

    private static final Logger log = LoggerFactory.getLogger(RetrievalOrchestrator.class);

    private final Map<String, Retriever> retrievers;
    private final Executor executor;

    /**
     * Sequential execution (no parallelism).
     */
    public RetrievalOrchestrator(Map<String, Retriever> retrievers) {
        this(retrievers, null);
    }

    /**
     * @param executor if non-null, routes execute in parallel; otherwise sequential
     */
    public RetrievalOrchestrator(Map<String, Retriever> retrievers, Executor executor) {
        this.retrievers = Objects.requireNonNull(retrievers, "retrievers must not be null");
        this.executor = executor;
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

        // 3. Execute routes — parallel when executor is set, sequential otherwise
        if (executor != null && routeConfigMap.size() > 1) {
            return executeParallel(retrievalQuery, routeConfigMap, snapshotIds);
        } else {
            return executeSequential(retrievalQuery, routeConfigMap, snapshotIds);
        }
    }

    /**
     * Sequential execution — one route at a time.
     */
    private OrchestratorResult executeSequential(
            RetrievalQuery retrievalQuery,
            Map<String, RouteConfig> routeConfigMap,
            List<String> snapshotIds) {

        List<RouteTrace> traces = new ArrayList<>();
        List<RetrievalCandidate> allCandidates = new ArrayList<>();

        for (var entry : routeConfigMap.entrySet()) {
            executeRoute(retrievalQuery, snapshotIds, entry.getKey(), entry.getValue(),
                    allCandidates, traces);
        }

        return new OrchestratorResult(allCandidates, traces);
    }

    /**
     * Parallel execution — all routes via CompletableFuture + DomainContext propagation.
     */
    private OrchestratorResult executeParallel(
            RetrievalQuery retrievalQuery,
            Map<String, RouteConfig> routeConfigMap,
            List<String> snapshotIds) {

        ConcurrentLinkedQueue<RetrievalCandidate> allCandidates = new ConcurrentLinkedQueue<>();
        ConcurrentLinkedQueue<RouteTrace> traces = new ConcurrentLinkedQueue<>();
        List<CompletableFuture<Void>> futures = new ArrayList<>();

        for (var entry : routeConfigMap.entrySet()) {
            String routeName = entry.getKey();
            RouteConfig routeCfg = entry.getValue();

            // Pre-check: skip routes that definitely don't need execution
            Retriever retriever = retrievers.get(routeName);
            if (retriever == null) {
                traces.add(new RouteTrace(routeName, false, 0, "not_registered", 0));
                continue;
            }
            if (ServingConstants.ROUTE_DENSE_VECTOR.equals(routeName)
                    && (retrievalQuery.queryEmbedding() == null || retrievalQuery.queryEmbedding().length == 0)) {
                traces.add(new RouteTrace(routeName, false, 0, "no_embedding", 0));
                continue;
            }

            CompletableFuture<Void> future = CompletableFuture.runAsync(
                    DomainContext.wrapRunnable(() ->
                            executeRoute(retrievalQuery, snapshotIds, routeName, routeCfg,
                                    allCandidates, traces)),
                    executor);
            futures.add(future);
        }

        // Wait for all routes to complete
        CompletableFuture.allOf(futures.toArray(CompletableFuture[]::new)).join();

        return new OrchestratorResult(new ArrayList<>(allCandidates), new ArrayList<>(traces));
    }

    /**
     * Execute a single route — shared logic for both sequential and parallel modes.
     * Adds results directly into the provided mutable collections.
     */
    private void executeRoute(
            RetrievalQuery retrievalQuery,
            List<String> snapshotIds,
            String routeName,
            RouteConfig routeCfg,
            Collection<RetrievalCandidate> allCandidates,
            Collection<RouteTrace> traces) {

        Retriever retriever = retrievers.get(routeName);
        if (retriever == null) {
            traces.add(new RouteTrace(routeName, false, 0, "not_registered", 0));
            return;
        }

        // Auto-skip dense_vector when no embedding available
        if (ServingConstants.ROUTE_DENSE_VECTOR.equals(routeName)
                && (retrievalQuery.queryEmbedding() == null || retrievalQuery.queryEmbedding().length == 0)) {
            traces.add(new RouteTrace(routeName, false, 0, "no_embedding", 0));
            return;
        }

        // Execute with exception isolation
        long start = System.nanoTime();
        List<RetrievalCandidate> candidates;
        try {
            candidates = retriever.retrieve(retrievalQuery, snapshotIds, routeCfg.topK());
        } catch (Exception e) {
            double latencyMs = (System.nanoTime() - start) / 1_000_000.0;
            log.warn("[retrieve] route={} failed: {}", routeName, e.getMessage());
            traces.add(new RouteTrace(routeName, false, 0, e.getMessage(), latencyMs));
            return;
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

}
