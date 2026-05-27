package com.coremasterkb.serving.domain;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Tests that all domain records provide correct null defaults.
 */
@DisplayName("Domain Record Defaults")
class DomainRecordDefaultsTest {

    @Nested
    @DisplayName("SearchRequest")
    class SearchRequestTests {
        @Test
        @DisplayName("null scope defaults to empty map")
        void nullScopeDefaultsToEmptyMap() {
            var req = new SearchRequest("test", null, null, false, "cloud_core_network", null, null);
            assertThat(req.scope()).isEmpty();
            assertThat(req.entities()).isEmpty();
            assertThat(req.mode()).isEqualTo("evidence");
        }
    }

    @Nested
    @DisplayName("ContextPack")
    class ContextPackTests {
        @Test
        @DisplayName("null collections default to empty")
        void nullCollectionsDefaultToEmpty() {
            var pack = new ContextPack(null, null, null, null, null, null, null, null);
            assertThat(pack.items()).isEmpty();
            assertThat(pack.relations()).isEmpty();
            assertThat(pack.sources()).isEmpty();
            assertThat(pack.evidenceGroups()).isEmpty();
            assertThat(pack.issues()).isEmpty();
            assertThat(pack.suggestions()).isEmpty();
            assertThat(pack.debug()).isEmpty();
        }
    }

    @Nested
    @DisplayName("ContextItem")
    class ContextItemTests {
        @Test
        @DisplayName("null fields default correctly")
        void nullFieldsDefaultCorrectly() {
            var item = new ContextItem("id", "kind", "role", "text", 0.5,
                    "title", null, null, "srcId", null, null, null, null, null, null, null);
            assertThat(item.blockType()).isEqualTo("unknown");
            assertThat(item.semanticRole()).isEqualTo("unknown");
            assertThat(item.sourceRefs()).isEmpty();
            assertThat(item.metadata()).isEmpty();
            assertThat(item.routeSources()).isEmpty();
            assertThat(item.evidenceRole()).isEmpty();
            assertThat(item.citation()).isEmpty();
        }
    }

    @Nested
    @DisplayName("ActiveScope")
    class ActiveScopeTests {
        @Test
        @DisplayName("null collections default to empty")
        void nullCollectionsDefaultToEmpty() {
            var scope = new ActiveScope("rel", "build", null, null);
            assertThat(scope.snapshotIds()).isEmpty();
            assertThat(scope.documentSnapshotMap()).isEmpty();
        }
    }

    @Nested
    @DisplayName("ScoreChain")
    class ScoreChainTests {
        @Test
        @DisplayName("null routeSources defaults to empty list")
        void nullRouteSourcesDefaultsToEmpty() {
            var chain = new ScoreChain(0.5, 0.3, 0.4, null);
            assertThat(chain.routeSources()).isEmpty();
        }
    }

    @Nested
    @DisplayName("RetrievalCandidate")
    class RetrievalCandidateTests {
        @Test
        @DisplayName("null metadata defaults to empty map")
        void nullMetadataDefaultsToEmptyMap() {
            var cand = new RetrievalCandidate("unit1", 0.9, "bm25", null, null);
            assertThat(cand.metadata()).isEmpty();
        }
    }

    @Nested
    @DisplayName("RetrievalRoutePlan")
    class RetrievalRoutePlanTests {
        @Test
        @DisplayName("null fields default correctly")
        void nullFieldsDefaultCorrectly() {
            var plan = new RetrievalRoutePlan(null, null, null, null, null, null);
            assertThat(plan.routes()).isEmpty();
            assertThat(plan.filters()).isEmpty();
            assertThat(plan.fusion()).isNotNull();
            assertThat(plan.fusion().k()).isEqualTo(60);
            assertThat(plan.rerank()).isNotNull();
            assertThat(plan.assembly()).isNotNull();
            assertThat(plan.expansion()).isNotNull();
        }
    }

    @Nested
    @DisplayName("QueryUnderstanding")
    class QueryUnderstandingTests {
        @Test
        @DisplayName("null fields default correctly")
        void nullFieldsDefaultCorrectly() {
            var qu = new QueryUnderstanding("q", null, null, null, null, null, null, null, null);
            assertThat(qu.intent()).isEqualTo("general");
            assertThat(qu.subQueries()).isEmpty();
            assertThat(qu.entities()).isEmpty();
            assertThat(qu.scope()).isEmpty();
            assertThat(qu.keywords()).isEmpty();
            assertThat(qu.evidenceNeed()).isNotNull();
            assertThat(qu.ambiguities()).isEmpty();
            assertThat(qu.source()).isEqualTo("rule");
        }
    }

    @Nested
    @DisplayName("Issue")
    class IssueTests {
        @Test
        @DisplayName("null detail defaults to empty map")
        void nullDetailDefaultsToEmptyMap() {
            var issue = new Issue("warning", "msg", null);
            assertThat(issue.detail()).isEmpty();
        }
    }

    @Nested
    @DisplayName("Trace")
    class TraceTests {
        @Test
        @DisplayName("null stages default to empty list")
        void nullStagesDefaultToEmpty() {
            var trace = new Trace("req1", null, 0);
            assertThat(trace.stages()).isEmpty();
        }
    }

    @Nested
    @DisplayName("OrchestratorResult")
    class OrchestratorResultTests {
        @Test
        @DisplayName("empty factory returns empty result")
        void emptyFactory() {
            var result = OrchestratorResult.empty();
            assertThat(result.candidates()).isEmpty();
            assertThat(result.routeTraces()).isEmpty();
        }

        @Test
        @DisplayName("null fields default to empty")
        void nullFieldsDefaultToEmpty() {
            var result = new OrchestratorResult(null, null);
            assertThat(result.candidates()).isEmpty();
            assertThat(result.routeTraces()).isEmpty();
        }
    }

    @Nested
    @DisplayName("FusionConfig")
    class FusionConfigTests {
        @Test
        @DisplayName("null method defaults to weighted_rrf")
        void nullMethodDefaultsToWeightedRrf() {
            var config = new FusionConfig(null, 60);
            assertThat(config.method()).isEqualTo("weighted_rrf");
        }
    }

    @Nested
    @DisplayName("RerankConfig")
    class RerankConfigTests {
        @Test
        @DisplayName("null fields default to score")
        void nullFieldsDefaultToScore() {
            var config = new RerankConfig(null, null);
            assertThat(config.method()).isEqualTo("score");
            assertThat(config.fallback()).isEqualTo("score");
        }
    }

    @Nested
    @DisplayName("SubQuery")
    class SubQueryTests {
        @Test
        @DisplayName("null fields default correctly")
        void nullFieldsDefaultCorrectly() {
            var sq = new SubQuery("text", null, null);
            assertThat(sq.intent()).isEqualTo("general");
            assertThat(sq.entities()).isEmpty();
        }
    }

    @Nested
    @DisplayName("EntityRef")
    class EntityRefTests {
        @Test
        @DisplayName("null fields default to empty string")
        void nullFieldsDefaultToEmpty() {
            var ref = new EntityRef(null, "SMF", null);
            assertThat(ref.type()).isEmpty();
            assertThat(ref.normalizedName()).isEmpty();
        }
    }

    @Nested
    @DisplayName("SourceRef")
    class SourceRefTests {
        @Test
        @DisplayName("null maps default to empty")
        void nullMapsDefaultToEmpty() {
            var ref = new SourceRef("id", "key", "title", "path", null, null);
            assertThat(ref.scopeJson()).isEmpty();
            assertThat(ref.metadata()).isEmpty();
        }
    }

    @Nested
    @DisplayName("EvidenceGroup")
    class EvidenceGroupTests {
        @Test
        @DisplayName("null lists default to empty")
        void nullListsDefaultToEmpty() {
            var group = new EvidenceGroup("snap1", null, null);
            assertThat(group.itemIds()).isEmpty();
            assertThat(group.relationIds()).isEmpty();
        }
    }

    @Nested
    @DisplayName("EvidenceNeed")
    class EvidenceNeedTests {
        @Test
        @DisplayName("empty factory returns correct defaults")
        void emptyFactory() {
            var need = EvidenceNeed.empty();
            assertThat(need.preferredRoles()).isEmpty();
            assertThat(need.preferredBlocks()).isEmpty();
            assertThat(need.needsComparison()).isFalse();
            assertThat(need.needsCitation()).isFalse();
        }
    }

    @Nested
    @DisplayName("RetrievalQuery")
    class RetrievalQueryTests {
        @Test
        @DisplayName("null fields default correctly")
        void nullFieldsDefaultCorrectly() {
            var query = new RetrievalQuery("q", null, null, null, null, null, null);
            assertThat(query.keywords()).isEmpty();
            assertThat(query.entities()).isEmpty();
            assertThat(query.subQueries()).isEmpty();
            assertThat(query.intent()).isEqualTo("general");
            assertThat(query.scope()).isEmpty();
        }
    }
}
