package com.coremasterkb.serving.evidence;

import com.coremasterkb.serving.domain.ContextItem;
import com.coremasterkb.serving.domain.EvidenceNeed;
import com.coremasterkb.serving.domain.QueryUnderstanding;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("EvidenceRoleClassifier")
class EvidenceRoleClassifierTest {

    private EvidenceRoleClassifier classifier;

    @BeforeEach
    void setUp() {
        classifier = new EvidenceRoleClassifier();
    }

    private final QueryUnderstanding understanding = new QueryUnderstanding(
            "SMF配置", "concept_lookup", List.of(), List.of(), Map.of(), List.of(),
            EvidenceNeed.empty(), List.of(), "rule"
    );

    @Nested
    @DisplayName("empty / null input")
    class EmptyInput {
        @Test
        @DisplayName("null items returns empty list")
        void nullReturnsEmpty() {
            assertThat(classifier.classify(null, understanding)).isEmpty();
        }

        @Test
        @DisplayName("empty items returns empty list")
        void emptyReturnsEmpty() {
            assertThat(classifier.classify(List.of(), understanding)).isEmpty();
        }
    }

    @Nested
    @DisplayName("seed items — score thresholds")
    class SeedScoreThresholds {
        @Test
        @DisplayName("seed with high score → direct_answer")
        void seedHighScore() {
            var item = seedItem(0.8);
            var result = classifier.classify(List.of(item), understanding);
            assertThat(result.get(0).evidenceRole()).isEqualTo("direct_answer");
        }

        @Test
        @DisplayName("seed with medium score → support")
        void seedMediumScore() {
            var item = seedItem(0.5);
            var result = classifier.classify(List.of(item), understanding);
            assertThat(result.get(0).evidenceRole()).isEqualTo("support");
        }

        @Test
        @DisplayName("seed with low score → background")
        void seedLowScore() {
            var item = seedItem(0.2);
            var result = classifier.classify(List.of(item), understanding);
            assertThat(result.get(0).evidenceRole()).isEqualTo("background");
        }
    }

    @Nested
    @DisplayName("relation-based roles")
    class RelationBasedRoles {
        @Test
        @DisplayName("contrasts_with → contrast")
        void contrastsWithReturnsContrast() {
            var item = relatedItem(0.8, "contrasts_with");
            var result = classifier.classify(List.of(item), understanding);
            assertThat(result.get(0).evidenceRole()).isEqualTo("contrast");
        }

        @Test
        @DisplayName("elaborates → support")
        void elaboratesReturnsSupport() {
            var item = relatedItem(0.8, "elaborates");
            var result = classifier.classify(List.of(item), understanding);
            assertThat(result.get(0).evidenceRole()).isEqualTo("support");
        }

        @Test
        @DisplayName("conditions → support")
        void conditionsReturnsSupport() {
            var item = relatedItem(0.8, "conditions");
            var result = classifier.classify(List.of(item), understanding);
            assertThat(result.get(0).evidenceRole()).isEqualTo("support");
        }

        @Test
        @DisplayName("causes → support")
        void causesReturnsSupport() {
            var item = relatedItem(0.8, "causes");
            var result = classifier.classify(List.of(item), understanding);
            assertThat(result.get(0).evidenceRole()).isEqualTo("support");
        }

        @Test
        @DisplayName("results_in → support")
        void resultsInReturnsSupport() {
            var item = relatedItem(0.8, "results_in");
            var result = classifier.classify(List.of(item), understanding);
            assertThat(result.get(0).evidenceRole()).isEqualTo("support");
        }

        @Test
        @DisplayName("unknown relation → background")
        void unknownRelationReturnsBackground() {
            var item = relatedItem(0.8, "some_other_rel");
            var result = classifier.classify(List.of(item), understanding);
            assertThat(result.get(0).evidenceRole()).isEqualTo("background");
        }
    }

    @Nested
    @DisplayName("no relation, not seed")
    class NoRelationNotSeed {
        @Test
        @DisplayName("high score → support")
        void highScoreReturnsSupport() {
            var item = contextItem(0.6);
            var result = classifier.classify(List.of(item), understanding);
            assertThat(result.get(0).evidenceRole()).isEqualTo("support");
        }

        @Test
        @DisplayName("low score → background")
        void lowScoreReturnsBackground() {
            var item = contextItem(0.2);
            var result = classifier.classify(List.of(item), understanding);
            assertThat(result.get(0).evidenceRole()).isEqualTo("background");
        }
    }

    // Helpers
    private ContextItem seedItem(double score) {
        return new ContextItem("id", "retrieval_unit", "seed", "text", score,
                "title", "unknown", "unknown", "srcId", "seed",
                null, null, null, null, null, null);
    }

    private ContextItem relatedItem(double score, String relation) {
        return new ContextItem("id", "retrieval_unit", "context", "text", score,
                "title", "unknown", "unknown", "srcId", relation,
                null, null, null, null, null, null);
    }

    private ContextItem contextItem(double score) {
        return new ContextItem("id", "retrieval_unit", "context", "text", score,
                "title", "unknown", "unknown", "srcId", null,
                null, null, null, null, null, null);
    }
}
