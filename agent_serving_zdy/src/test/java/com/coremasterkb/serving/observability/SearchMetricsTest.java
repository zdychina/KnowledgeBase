package com.coremasterkb.serving.observability;

import io.micrometer.prometheus.PrometheusConfig;
import io.micrometer.prometheus.PrometheusMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Verifies the six required metric families are exposed with the exact
 * Prometheus names and labels mandated by the observability spec.
 */
@DisplayName("SearchMetrics")
class SearchMetricsTest {

    private PrometheusMeterRegistry registry;
    private SearchMetrics metrics;

    @BeforeEach
    void setUp() {
        registry = new PrometheusMeterRegistry(PrometheusConfig.DEFAULT);
        metrics = new SearchMetrics(registry);
    }

    @Test
    @DisplayName("exposes all six metric families with correct names and labels")
    void exposesAllMetrics() {
        metrics.recordSearchDuration(42.0);
        metrics.recordRouteCandidates("lexical_bm25", 12);
        metrics.recordRerankDuration(7.5);
        metrics.recordRerankFallback("llm");
        metrics.recordIntent("command_usage");
        metrics.recordScopeEmpty();

        String scrape = registry.scrape();

        // Duration histograms: DistributionSummary exposes _count/_sum/_bucket; the
        // _ms unit is carried in the name (no baseUnit suffix appended).
        assertThat(scrape).contains("serving_search_duration_ms_count");
        assertThat(scrape).contains("serving_search_duration_ms_bucket");
        assertThat(scrape).contains("serving_rerank_duration_ms_count");

        // Per-route candidate distribution carries the route label.
        assertThat(scrape).contains("serving_retrieval_candidates_count");
        assertThat(scrape).contains("route=\"lexical_bm25\"");

        // Counters: Prometheus appends _total automatically; required labels present.
        assertThat(scrape).contains("serving_rerank_fallback_total");
        assertThat(scrape).contains("method=\"llm\"");
        assertThat(scrape).contains("serving_query_intent_total");
        assertThat(scrape).contains("intent=\"command_usage\"");
        assertThat(scrape).contains("serving_scope_empty_total");
    }

    @Test
    @DisplayName("null/blank tag values fall back to 'unknown' without throwing")
    void nullTagsHandled() {
        metrics.recordRouteCandidates(null, 0);
        metrics.recordRerankFallback("");
        metrics.recordIntent(null);

        String scrape = registry.scrape();
        assertThat(scrape).contains("route=\"unknown\"");
        assertThat(scrape).contains("method=\"unknown\"");
        assertThat(scrape).contains("intent=\"unknown\"");
    }
}
