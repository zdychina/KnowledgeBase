package com.coremasterkb.serving.domain;

/**
 * Trace entry for a single retrieval route execution.
 *
 * @param name            route name
 * @param attempted       whether the route was attempted
 * @param candidateCount  number of candidates produced
 * @param skippedReason   reason for skipping (null if not skipped)
 * @param latencyMs       execution latency in milliseconds
 */
public record RouteTrace(
        String name,
        boolean attempted,
        int candidateCount,
        String skippedReason,
        double latencyMs
) {
}
