package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.EntityRef;
import com.coremasterkb.serving.domain.QueryUnderstanding;
import com.coremasterkb.serving.domain.ServingConstants;
import com.coremasterkb.serving.infrastructure.LlmClient;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@DisplayName("QueryUnderstandingEngine")
class QueryUnderstandingEngineTest {

    private QueryUnderstandingEngine engine;
    private LlmClient llmClient;

    @BeforeAll
    static void warmUpJieba() {
        // Pre-warm jieba to avoid first-test slowness
        new com.huaban.analysis.jieba.JiebaSegmenter().sentenceProcess("预热");
    }

    @BeforeEach
    void setUp() {
        llmClient = mock(LlmClient.class);
        when(llmClient.isAvailable()).thenReturn(false);
        engine = new QueryUnderstandingEngine(llmClient);
    }

    @Nested
    @DisplayName("intent detection — rule fallback")
    class IntentDetection {
        @Test
        @DisplayName("command_usage: ADD SMFPARTNER")
        void commandUsageIntent() {
            var result = engine.understand("ADD SMFPARTNER 命令怎么写", null);
            assertThat(result.intent()).isEqualTo(ServingConstants.INTENT_COMMAND_USAGE);
            assertThat(result.source()).isEqualTo("rule");
        }

        @Test
        @DisplayName("troubleshooting: 故障排查")
        void troubleshootingIntent() {
            var result = engine.understand("SMF故障排查方法", null);
            assertThat(result.intent()).isEqualTo(ServingConstants.INTENT_TROUBLESHOOT);
        }

        @Test
        @DisplayName("concept_lookup: 是什么")
        void conceptLookupIntent() {
            var result = engine.understand("AMF是什么", null);
            assertThat(result.intent()).isEqualTo(ServingConstants.INTENT_CONCEPT_LOOKUP);
        }

        @Test
        @DisplayName("procedure: 步骤")
        void procedureIntent() {
            var result = engine.understand("UPF开通的步骤", null);
            assertThat(result.intent()).isEqualTo(ServingConstants.INTENT_PROCEDURE);
        }

        @Test
        @DisplayName("comparison: 区别")
        void comparisonIntent() {
            var result = engine.understand("UDG和UNC的区别", null);
            assertThat(result.intent()).isEqualTo(ServingConstants.INTENT_COMPARISON);
        }

        @Test
        @DisplayName("navigational: normalized to general by LLM_INTENT_TO_INTERNAL")
        void navigationalIntent() {
            // Note: "navigational" is mapped to "general" in LLM_INTENT_TO_INTERNAL,
            // so rule-based navigational queries normalize to "general"
            var result = engine.understand("如何找到UDG", null);
            assertThat(result.intent()).isEqualTo(ServingConstants.INTENT_GENERAL);
        }

        @Test
        @DisplayName("general: fallback for unmatched")
        void generalIntent() {
            var result = engine.understand("你好", null);
            assertThat(result.intent()).isEqualTo(ServingConstants.INTENT_GENERAL);
        }
    }

    @Nested
    @DisplayName("scope extraction")
    class ScopeExtraction {
        @Test
        @DisplayName("extracts network elements from query")
        void extractsNetworkElements() {
            var result = engine.understand("SMF配置方法", null);
            assertThat(result.scope()).containsKey("network_elements");
            @SuppressWarnings("unchecked")
            List<String> nes = (List<String>) result.scope().get("network_elements");
            assertThat(nes).contains("SMF");
        }

        @Test
        @DisplayName("extracts products from query")
        void extractsProducts() {
            var result = engine.understand("UDG产品介绍", null);
            assertThat(result.scope()).containsKey("products");
            @SuppressWarnings("unchecked")
            List<String> prods = (List<String>) result.scope().get("products");
            assertThat(prods).contains("UDG");
        }

        @Test
        @DisplayName("no scope when no entities present")
        void noScopeNoEntities() {
            var result = engine.understand("天气怎么样", null);
            assertThat(result.scope()).isEmpty();
        }
    }

    @Nested
    @DisplayName("entity extraction")
    class EntityExtraction {
        @Test
        @DisplayName("ADD SMFPARTNER extracts command entity")
        void commandEntityExtracted() {
            var result = engine.understand("ADD SMFPARTNER", null);
            assertThat(result.entities()).anyMatch(e -> "command".equals(e.type()));
        }

        @Test
        @DisplayName("Chinese op map: 新增SMF")
        void chineseOpMapExtraction() {
            var result = engine.understand("新增SMF", null);
            assertThat(result.entities()).anyMatch(e -> "command".equals(e.type()));
        }
    }

    @Nested
    @DisplayName("keyword extraction")
    class KeywordExtraction {
        @Test
        @DisplayName("keywords extracted via jieba")
        void keywordsExtracted() {
            var result = engine.understand("SMF配置方法", null);
            assertThat(result.keywords()).isNotEmpty();
        }

        @Test
        @DisplayName("stopwords filtered out")
        void stopwordsFiltered() {
            var result = engine.understand("请问SMF的配置方法是什么", null);
            assertThat(result.keywords()).doesNotContain("的", "是", "什么", "请问");
        }
    }

    @Nested
    @DisplayName("original query preserved")
    class OriginalQueryPreserved {
        @Test
        @DisplayName("original query is preserved in result")
        void originalQueryPreserved() {
            var result = engine.understand("SMF配置", null);
            assertThat(result.originalQuery()).isEqualTo("SMF配置");
        }
    }
}
