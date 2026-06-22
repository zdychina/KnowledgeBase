package com.coremasterkb.serving.domain;

/**
 * Trace step for a reranking attempt.
 *
 * @param provider        rerank provider name
 * @param attempted       whether reranking was attempted
 * @param succeeded       whether reranking succeeded
 * @param fallbackReason  reason for fallback (null if no fallback)
 * @param latencyMs       execution latency in milliseconds
 * @param countBefore     candidate count before reranking
 * @param countAfter      candidate count after reranking
 */
public record RerankTraceStep(
        String provider,
        boolean attempted,
        boolean succeeded,
        String fallbackReason,
        double latencyMs,
        int countBefore,
        int countAfter
) {
}
