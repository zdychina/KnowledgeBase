package com.coremasterkb.serving;

import com.coremasterkb.serving.application.QueryNormalizer;
import com.coremasterkb.serving.domain.*;
import com.coremasterkb.serving.pipeline.IdentityFusion;
import com.coremasterkb.serving.pipeline.RRFFusion;
import com.coremasterkb.serving.util.JsonUtils;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Unit tests for core serving components.
 * These tests do NOT require a running Spring context or database.
 */
class AgentServingApplicationTests {

    // -------------------------------------------------------------------------
    // QueryNormalizer
    // -------------------------------------------------------------------------

    @Test
    void normalizer_rulesDetectCommandIntent() {
        QueryNormalizer norm = new QueryNormalizer(null);
        NormalizedQuery result = norm.normalize("ADD USER_GROUP 怎么写");
        assertThat(result.intent()).isEqualTo("command_usage");
        assertThat(result.keywords()).isNotEmpty();
    }

    @Test
    void normalizer_detectsTroubleshootIntent() {
        QueryNormalizer norm = new QueryNormalizer(null);
        NormalizedQuery result = norm.normalize("AMF 故障 排查");
        assertThat(result.intent()).isEqualTo("troubleshooting");
    }

    @Test
    void normalizer_extractsVersion() {
        QueryNormalizer norm = new QueryNormalizer(null);
        NormalizedQuery result = norm.normalize("V300R002 AMF 配置");
        assertThat(result.scope()).containsKey("version");
        assertThat(result.scope().get("version")).isEqualTo("V300R002");
    }

    @Test
    void normalizer_filtersStopwords() {
        QueryNormalizer norm = new QueryNormalizer(null);
        NormalizedQuery result = norm.normalize("什么是 AMF");
        // "什么是" is a stopword sequence; "AMF" should be in keywords
        assertThat(result.keywords()).contains("AMF");
        assertThat(result.keywords()).doesNotContain("的", "是", "什么");
    }

    // -------------------------------------------------------------------------
    // IdentityFusion
    // -------------------------------------------------------------------------

    @Test
    void identityFusion_deduplicatesKeepingHigherScore() {
        IdentityFusion fusion = new IdentityFusion();
        QueryPlan plan = new QueryPlan(null, null, null, null, null, null, null, null, null, null);

        RetrievalCandidate c1 = new RetrievalCandidate("id1", 0.5, "fts_bm25", Map.of());
        RetrievalCandidate c2 = new RetrievalCandidate("id1", 0.9, "fts_bm25", Map.of()); // higher
        RetrievalCandidate c3 = new RetrievalCandidate("id2", 0.3, "fts_bm25", Map.of());

        List<RetrievalCandidate> result = fusion.fuse(List.of(c1, c2, c3), plan);

        assertThat(result).hasSize(2);
        assertThat(result.get(0).retrievalUnitId()).isEqualTo("id1");
        assertThat(result.get(0).score()).isEqualTo(0.9);
    }

    @Test
    void identityFusion_sortsByScoreDescending() {
        IdentityFusion fusion = new IdentityFusion();
        QueryPlan plan = new QueryPlan(null, null, null, null, null, null, null, null, null, null);

        RetrievalCandidate c1 = new RetrievalCandidate("id1", 0.2, "s", Map.of());
        RetrievalCandidate c2 = new RetrievalCandidate("id2", 0.8, "s", Map.of());
        RetrievalCandidate c3 = new RetrievalCandidate("id3", 0.5, "s", Map.of());

        List<RetrievalCandidate> result = fusion.fuse(List.of(c1, c2, c3), plan);
        assertThat(result.get(0).score()).isEqualTo(0.8);
        assertThat(result.get(2).score()).isEqualTo(0.2);
    }

    // -------------------------------------------------------------------------
    // RRFFusion
    // -------------------------------------------------------------------------

    @Test
    void rrfFusion_combinesMultipleSources() {
        RRFFusion fusion = new RRFFusion();
        RetrieverConfig cfg = new RetrieverConfig(List.of("fts_bm25"), "rrf", 60);
        QueryPlan plan = new QueryPlan(null, null, null, null, null, null,
                new RetrievalBudget(), new ExpansionConfig(), cfg, new RerankerConfig());

        // id1 appears in both sources → higher RRF score
        RetrievalCandidate c1s1 = new RetrievalCandidate("id1", 0.9, "source1", Map.of());
        RetrievalCandidate c1s2 = new RetrievalCandidate("id1", 0.7, "source2", Map.of());
        RetrievalCandidate c2s1 = new RetrievalCandidate("id2", 0.8, "source1", Map.of());

        List<RetrievalCandidate> result = fusion.fuse(List.of(c1s1, c1s2, c2s1), plan);

        assertThat(result).isNotEmpty();
        // id1 should come first (appears in 2 sources → higher RRF)
        assertThat(result.get(0).retrievalUnitId()).isEqualTo("id1");
    }

    // -------------------------------------------------------------------------
    // JsonUtils
    // -------------------------------------------------------------------------

    @Test
    void jsonUtils_parseSourceRefs_extractsIds() {
        String json = "{\"raw_segment_ids\": [\"seg1\", \"seg2\"]}";
        List<String> ids = JsonUtils.parseSourceRefs(json);
        assertThat(ids).containsExactly("seg1", "seg2");
    }

    @Test
    void jsonUtils_parseSourceRefs_returnsEmptyOnNull() {
        assertThat(JsonUtils.parseSourceRefs(null)).isEmpty();
        assertThat(JsonUtils.parseSourceRefs("")).isEmpty();
        assertThat(JsonUtils.parseSourceRefs("invalid")).isEmpty();
    }

    @Test
    void jsonUtils_parseTargetRef_singleId() {
        String json = "{\"raw_segment_id\": \"seg99\"}";
        assertThat(JsonUtils.parseTargetRef(json)).containsExactly("seg99");
    }

    @Test
    void jsonUtils_parseTargetRef_multipleIds() {
        String json = "{\"raw_segment_ids\": [\"s1\", \"s2\"]}";
        assertThat(JsonUtils.parseTargetRef(json)).containsExactly("s1", "s2");
    }

    @Test
    void jsonUtils_safeJsonParse_mapInput() {
        Map<String, Object> input = Map.of("key", "value");
        assertThat(JsonUtils.safeJsonParse(input)).isEqualTo(input);
    }

    @Test
    void jsonUtils_safeJsonParse_validJson() {
        String json = "{\"a\": 1}";
        Map<String, Object> result = JsonUtils.safeJsonParse(json);
        assertThat(result).containsKey("a");
    }

    @Test
    void jsonUtils_safeJsonParse_invalidReturnsEmpty() {
        assertThat(JsonUtils.safeJsonParse("not-json")).isEmpty();
    }

    // -------------------------------------------------------------------------
    // Domain records
    // -------------------------------------------------------------------------

    @Test
    void retrievalBudget_defaults() {
        RetrievalBudget b = new RetrievalBudget();
        assertThat(b.maxItems()).isEqualTo(10);
        assertThat(b.maxExpanded()).isEqualTo(20);
        assertThat(b.recallMultiplier()).isEqualTo(5);
    }

    @Test
    void expansionConfig_defaults() {
        ExpansionConfig cfg = new ExpansionConfig();
        assertThat(cfg.enableRelationExpansion()).isTrue();
        assertThat(cfg.maxRelationDepth()).isEqualTo(2);
        assertThat(cfg.relationTypes()).contains("previous", "next");
    }

    @Test
    void normalizedQuery_withScope_createsNewRecord() {
        NormalizedQuery nq = new NormalizedQuery("q", "general",
                List.of(), Map.of(), List.of(), List.of());
        Map<String, Object> newScope = Map.of("version", "V300R002");
        NormalizedQuery updated = nq.withScope(newScope);
        assertThat(updated.scope()).containsKey("version");
        assertThat(nq.scope()).doesNotContainKey("version"); // original unchanged
    }
}
