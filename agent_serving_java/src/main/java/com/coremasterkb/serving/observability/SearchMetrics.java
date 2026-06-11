package com.coremasterkb.serving.observability;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.DistributionSummary;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.stereotype.Component;

/**
 * Micrometer instrumentation for the search pipeline.
 */
@Component
public class SearchMetrics {

    private final MeterRegistry registry;
    private final DistributionSummary searchDuration;
    private final DistributionSummary rerankDuration;

    public SearchMetrics(MeterRegistry registry) {
        this.registry = registry;
        this.searchDuration = DistributionSummary.builder("serving_search_duration_ms")
                .description("End-to-end /search pipeline latency in milliseconds")
                .publishPercentileHistogram()
                .register(registry);
        this.rerankDuration = DistributionSummary.builder("serving_rerank_duration_ms")
                .description("Rerank stage latency in milliseconds")
                .publishPercentileHistogram()
                .register(registry);
    }

    public void recordSearchDuration(double millis) {
        searchDuration.record(millis);
    }

    public void recordRouteCandidates(String route, int count) {
        DistributionSummary.builder("serving_retrieval_candidates")
                .description("Candidate count per retrieval route execution")
                .tag("route", route != null && !route.isBlank() ? route : "unknown")
                .register(registry)
                .record(count);
    }

    public void recordRerankDuration(double millis) {
        rerankDuration.record(millis);
    }

    public void recordRerankFallback(String method) {
        Counter.builder("serving_rerank_fallback")
                .description("Rerank tier that produced the final ranking")
                .tag("method", method != null && !method.isBlank() ? method : "unknown")
                .register(registry)
                .increment();
    }

    public void recordIntent(String intent) {
        Counter.builder("serving_query_intent")
                .description("Query intent distribution")
                .tag("intent", intent != null && !intent.isBlank() ? intent : "unknown")
                .register(registry)
                .increment();
    }

    public void recordScopeEmpty() {
        Counter.builder("serving_scope_empty")
                .description("Requests with empty query scope that produced no seed result")
                .register(registry)
                .increment();
    }
}
