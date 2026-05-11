package com.coremasterkb.serving.domain;

import java.util.List;

/**
 * Result produced by the retrieval orchestrator.
 *
 * @param candidates   merged and ranked candidates; defaults to empty list
 * @param routeTraces  trace entries for each route; defaults to empty list
 */
public record OrchestratorResult(
        List<RetrievalCandidate> candidates,
        List<RouteTrace> routeTraces
) {
    public OrchestratorResult {
        if (candidates == null) candidates = List.of();
        if (routeTraces == null) routeTraces = List.of();
    }

    public static OrchestratorResult empty() {
        return new OrchestratorResult(List.of(), List.of());
    }
}
