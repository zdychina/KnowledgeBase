package com.coremasterkb.serving.observability;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.DistributionSummary;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.stereotype.Component;

/**
 * Micrometer instrumentation for the search pipeline.
 *
 * <p>All recordings are O(1) lock-free atomic updates into in-memory meters;
 * values are exposed via the pull-based {@code /actuator/prometheus} scrape
 * endpoint, so metric collection never blocks the request thread nor measurably
 * affects retrieval latency.</p>
 *
 * <p><b>Naming note:</b> counter meters are registered WITHOUT a {@code _total}
 * suffix because the Prometheus registry appends it automatically — e.g.
 * {@code serving_query_intent} is scraped as {@code serving_query_intent_total}.
 * Duration meters use {@link DistributionSummary} recording raw millisecond
 * values (name already carries the {@code _ms} unit), exposed as a histogram
 * via {@code publishPercentileHistogram()}.</p>
 *
 * <p>Exposed metric families:</p>
 * <ul>
 *   <li>{@code serving_search_duration_ms} — end-to-end latency histogram</li>
 *   <li>{@code serving_retrieval_candidates{route}} — candidate count per route</li>
 *   <li>{@code serving_rerank_duration_ms} — rerank latency histogram</li>
 *   <li>{@code serving_rerank_fallback_total{method}} — rerank tier that won (model/llm/score)</li>
 *   <li>{@code serving_query_intent_total{intent}} — intent distribution</li>
 *   <li>{@code serving_scope_empty_total} — empty-scope no-result count</li>
 * </ul>
 */
@Component
public class SearchMetrics {

    private final MeterRegistry registry;

    // No-tag duration histograms are cached; tagged meters are resolved per call
    // (Micrometer caches them internally by meter id, so this is cheap).
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

    /** Full-pipeline latency (ms). Recorded for every request, including failures. */
    public void recordSearchDuration(double millis) {
        searchDuration.record(millis);
    }

    /** Candidate count produced by a single retrieval route execution, tagged by route. */
    public void recordRouteCandidates(String route, int count) {
        DistributionSummary.builder("serving_retrieval_candidates")
                .description("Candidate count per retrieval route execution")
                .tag("route", route != null && !route.isBlank() ? route : "unknown")
                .register(registry)
                .record(count);
    }

    /** Rerank stage latency (ms). */
    public void recordRerankDuration(double millis) {
        rerankDuration.record(millis);
    }

    /**
     * Records which rerank tier ultimately produced the ranking (model | llm | score).
     * Fallback rate alerts can be derived as {@code sum(method!="model") / sum(all)}.
     */
    public void recordRerankFallback(String method) {
        Counter.builder("serving_rerank_fallback")
                .description("Rerank tier that produced the final ranking (cascade: model -> llm -> score)")
                .tag("method", method != null && !method.isBlank() ? method : "unknown")
                .register(registry)
                .increment();
    }

    /** Records the resolved query intent for distribution analysis. */
    public void recordIntent(String intent) {
        Counter.builder("serving_query_intent")
                .description("Query intent distribution")
                .tag("intent", intent != null && !intent.isBlank() ? intent : "unknown")
                .register(registry)
                .increment();
    }

    /** Records a request that returned no seed result while the query scope was empty. */
    public void recordScopeEmpty() {
        Counter.builder("serving_scope_empty")
                .description("Requests with empty query scope that produced no seed result")
                .register(registry)
                .increment();
    }
}
