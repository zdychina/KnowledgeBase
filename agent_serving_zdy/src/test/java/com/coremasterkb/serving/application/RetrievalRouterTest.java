package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.*;
import com.coremasterkb.serving.domainpack.ServingDomainProfile;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.Set;

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

        // Per-intent route weights come from the domain route policy (complexity tiers
        // drive the built-in defaults; the domain pack overrides weights per intent).
        @Test
        @DisplayName("command_usage favors entity_exact over lexical (domain route policy)")
        void commandUsageWeights() {
            var understanding = commandUsageUnderstanding();
            var plan = router.route(understanding, ServingDomainProfile.defaults("test"));
            var entityExact = plan.routes().stream()
                    .filter(r -> "entity_exact".equals(r.name())).findFirst();
            var lexical = plan.routes().stream()
                    .filter(r -> "lexical_bm25".equals(r.name())).findFirst();
            assertThat(entityExact).isPresent();
            assertThat(lexical).isPresent();
            assertThat(entityExact.get().weight()).isGreaterThan(1.0);
            assertThat(entityExact.get().weight()).isGreaterThan(lexical.get().weight());
        }

        @Test
        @DisplayName("concept_lookup gives higher weight to dense (domain route policy)")
        void conceptLookupWeights() {
            var understanding = conceptLookupUnderstanding();
            var plan = router.route(understanding, ServingDomainProfile.defaults("test"));
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
                    new EvidenceNeed(List.of(), List.of(), true, false), List.of(), "rule", null
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

    @Nested
    @DisplayName("intent-aware graph expansion + rerank")
    class IntentAwareStrategy {

        private QueryUnderstanding intentU(String intent) {
            return new QueryUnderstanding("q", intent, List.of(), List.of(), Map.of(), List.of(),
                    EvidenceNeed.empty(), List.of(), "rule", null);
        }

        @Test
        @DisplayName("troubleshooting expands along the causal chain + cascade rerank")
        void troubleshooting() {
            var plan = router.route(intentU("troubleshooting"), null);
            assertThat(plan.assembly().relationExpansion()).isTrue();
            assertThat(plan.assembly().relationTypes()).contains("causes", "results_in");
            assertThat(plan.rerank().method()).isEqualTo("cascade");
        }

        @Test
        @DisplayName("comparison expands along contrasts_with")
        void comparison() {
            var plan = router.route(intentU("comparison"), null);
            assertThat(plan.assembly().relationExpansion()).isTrue();
            assertThat(plan.assembly().relationTypes()).contains("contrasts_with");
        }

        @Test
        @DisplayName("procedure expands along purposes/enables")
        void procedure() {
            var plan = router.route(intentU("procedure"), null);
            assertThat(plan.assembly().relationExpansion()).isTrue();
            assertThat(plan.assembly().relationTypes()).contains("purposes", "enables");
        }

        @Test
        @DisplayName("non-targeted intent keeps default (no forced expansion, score rerank)")
        void otherIntentUnchanged() {
            var plan = router.route(intentU("general"), null);
            assertThat(plan.assembly().relationExpansion()).isFalse();
            assertThat(plan.rerank().method()).isEqualTo("score");
        }

        @Test
        @DisplayName("domain pack intent_strategy overrides built-in expansion + rerank")
        void domainOverride() {
            Map<String, Object> ge = Map.of(
                    "enabled", true,
                    "relation_types", List.of("custom_rel"),
                    "max_expanded", 3);
            Map<String, Object> strategy = Map.of(
                    "troubleshooting", Map.of("graph_expand", ge, "rerank", "llm"));
            var profile = new ServingDomainProfile(
                    "d", Set.of(), Set.of(), Map.of(), List.of(), List.of(), Map.of(), strategy);

            var plan = router.route(intentU("troubleshooting"), profile);
            assertThat(plan.assembly().relationTypes()).containsExactly("custom_rel");
            assertThat(plan.assembly().maxExpanded()).isEqualTo(3);
            assertThat(plan.rerank().method()).isEqualTo("llm");
        }
    }

    @Test
    @DisplayName("scope propagated from understanding")
    void scopePropagated() {
        var understanding = new QueryUnderstanding(
                "SMF配置", "general", List.of(), List.of(),
                Map.of("network_elements", List.of("SMF")), List.of("SMF", "配置"),
                EvidenceNeed.empty(), List.of(), "rule", null
        );
        var plan = router.route(understanding, null);
        assertThat(plan.filters()).containsKey("network_elements");
    }

    // Helpers
    private QueryUnderstanding generalUnderstanding() {
        return new QueryUnderstanding("你好", "general", List.of(), List.of(),
                Map.of(), List.of(), EvidenceNeed.empty(), List.of(), "rule", null);
    }

    private QueryUnderstanding commandUsageUnderstanding() {
        return new QueryUnderstanding("ADD SMFPARTNER 命令怎么写", "command_usage", List.of(),
                List.of(), Map.of(), List.of(), EvidenceNeed.empty(), List.of(), "rule", null);
    }

    private QueryUnderstanding conceptLookupUnderstanding() {
        return new QueryUnderstanding("AMF是什么", "concept_lookup", List.of(),
                List.of(), Map.of(), List.of(), EvidenceNeed.empty(), List.of(), "rule", null);
    }
}
