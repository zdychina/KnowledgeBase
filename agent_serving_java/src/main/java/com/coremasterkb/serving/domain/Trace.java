package com.coremasterkb.serving.domain;

import java.util.List;

/**
 * End-to-end pipeline trace for a single request.
 *
 * @param requestId       unique request identifier
 * @param stages          individual pipeline stages; defaults to empty list
 * @param totalDurationMs total pipeline duration in milliseconds
 */
public record Trace(
        String requestId,
        List<TraceStage> stages,
        double totalDurationMs
) {
    public Trace {
        if (stages == null) stages = List.of();
    }
}
