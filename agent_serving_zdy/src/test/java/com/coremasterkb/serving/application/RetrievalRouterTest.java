package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("RetrievalRouter")
class RetrievalRouterTest {

    private RetrievalRouter router;

    @BeforeEach
    void setUp() {
        router = new RetrievalRouter();
    }

    @Nested
    @DisplayName("intent-based route weights")
    class IntentBasedWeights {
        @Test
        @DisplayName("default intent provides lexical + dense routes")
        void defaultIntent() {
            var understanding = generalUnderstanding();
            var plan = router.route(understanding, null);
            assertThat(plan.routes()).hasSizeGreaterThanOrEqualTo(2);
            assertThat(plan.routes().stream().map(RouteConfig::name))
                    .contains("lexical_bm25", "dense_vector");
        }

        @Test
        @DisplayName("command_usage gives higher weight to lexical")
        void commandUsageWeights() {
            var understanding = commandUsageUnderstanding();
            var plan = router.route(understanding, null);
            var lexical = plan.routes().stream()
                    .filter(r -> "lexical_bm25".equals(r.name())).findFirst();
            assertThat(lexical).isPresent();
            assertThat(lexical.get().weight()).isGreaterThan(1.0);
        }

        @Test
        @DisplayName("concept_lookup gives higher weight to dense")
        void conceptLookupWeights() {
            var understanding = conceptLookupUnderstanding();
            var plan = router.route(understanding, null);
            var dense = plan.routes().stream()
                    .filter(r -> "dense_vector".equals(r.name())).findFirst();
            assertThat(dense).isPresent();
            assertThat(dense.get().weight()).isGreaterThan(1.0);
        }
    }

    @Nested
    @DisplayName("fusion method selection")
    class FusionMethodSelection {
        @Test
        @DisplayName("multiple routes → weighted_rrf")
        void multipleRoutesWeightedRrf() {
            var understanding = generalUnderstanding();
            var plan = router.route(understanding, null);
            long enabled = plan.routes().stream().filter(RouteConfig::enabled).count();
            if (enabled > 1) {
                assertThat(plan.fusion().method()).isEqualTo("weighted_rrf");
            }
        }
    }

    @Nested
    @DisplayName("rerank method selection")
    class RerankMethodSelection {
        @Test
        @DisplayName("comparison intent with needsComparison → cascade rerank")
        void comparisonIntentCascadeRerank() {
            var understanding = new QueryUnderstanding(
                    "UDG和UNC的区别", "comparison", List.of(), List.of(), Map.of(), List.of(),
                    new EvidenceNeed(List.of(), List.of(), true, false), List.of(), "rule"
            );
            var plan = router.route(understanding, null);
            assertThat(plan.rerank().method()).isEqualTo("cascade");
        }

        @Test
        @DisplayName("general intent → score rerank")
        void generalIntentScoreRerank() {
            var understanding = generalUnderstanding();
            var plan = router.route(understanding, null);
            assertThat(plan.rerank().method()).isEqualTo("score");
        }
    }

    @Test
    @DisplayName("scope propagated from understanding")
    void scopePropagated() {
        var understanding = new QueryUnderstanding(
                "SMF配置", "general", List.of(), List.of(),
                Map.of("network_elements", List.of("SMF")), List.of("SMF", "配置"),
                EvidenceNeed.empty(), List.of(), "rule"
        );
        var plan = router.route(understanding, null);
        assertThat(plan.filters()).containsKey("network_elements");
    }

    // Helpers
    private QueryUnderstanding generalUnderstanding() {
        return new QueryUnderstanding("你好", "general", List.of(), List.of(),
                Map.of(), List.of(), EvidenceNeed.empty(), List.of(), "rule");
    }

    private QueryUnderstanding commandUsageUnderstanding() {
        return new QueryUnderstanding("ADD SMFPARTNER 命令怎么写", "command_usage", List.of(),
                List.of(), Map.of(), List.of(), EvidenceNeed.empty(), List.of(), "rule");
    }

    private QueryUnderstanding conceptLookupUnderstanding() {
        return new QueryUnderstanding("AMF是什么", "concept_lookup", List.of(),
                List.of(), Map.of(), List.of(), EvidenceNeed.empty(), List.of(), "rule");
    }
}
