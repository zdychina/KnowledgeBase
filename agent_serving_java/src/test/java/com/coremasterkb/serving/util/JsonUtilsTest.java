package com.coremasterkb.serving.util;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("JsonUtils")
class JsonUtilsTest {

    @Nested
    @DisplayName("parseSourceRefs")
    class ParseSourceRefs {
        @Test
        @DisplayName("null input returns empty list")
        void nullReturnsEmpty() {
            assertThat(JsonUtils.parseSourceRefs(null)).isEmpty();
        }

        @Test
        @DisplayName("blank input returns empty list")
        void blankReturnsEmpty() {
            assertThat(JsonUtils.parseSourceRefs("  ")).isEmpty();
        }

        @Test
        @DisplayName("valid source refs JSON returns list")
        void validJsonReturnsList() {
            String json = "{\"raw_segment_ids\": [\"seg1\", \"seg2\"]}";
            assertThat(JsonUtils.parseSourceRefs(json)).containsExactly("seg1", "seg2");
        }

        @Test
        @DisplayName("missing raw_segment_ids returns empty")
        void missingKeyReturnsEmpty() {
            String json = "{\"other_key\": []}";
            assertThat(JsonUtils.parseSourceRefs(json)).isEmpty();
        }

        @Test
        @DisplayName("invalid JSON returns empty list")
        void invalidJsonReturnsEmpty() {
            assertThat(JsonUtils.parseSourceRefs("not json")).isEmpty();
        }

        @Test
        @DisplayName("non-string items in list are skipped")
        void nonStringItemsSkipped() {
            String json = "{\"raw_segment_ids\": [123, \"seg1\", true]}";
            assertThat(JsonUtils.parseSourceRefs(json)).containsExactly("seg1");
        }
    }

    @Nested
    @DisplayName("parseTargetRef")
    class ParseTargetRef {
        @Test
        @DisplayName("null returns empty list")
        void nullReturnsEmpty() {
            assertThat(JsonUtils.parseTargetRef(null)).isEmpty();
        }

        @Test
        @DisplayName("single raw_segment_id returns list of one")
        void singleTargetRef() {
            String json = "{\"raw_segment_id\": \"seg1\"}";
            assertThat(JsonUtils.parseTargetRef(json)).containsExactly("seg1");
        }

        @Test
        @DisplayName("raw_segment_ids array returns list")
        void multipleTargetRefs() {
            String json = "{\"raw_segment_ids\": [\"seg1\", \"seg2\"]}";
            assertThat(JsonUtils.parseTargetRef(json)).containsExactly("seg1", "seg2");
        }

        @Test
        @DisplayName("invalid JSON returns empty")
        void invalidReturnsEmpty() {
            assertThat(JsonUtils.parseTargetRef("bad")).isEmpty();
        }

        @Test
        @DisplayName("empty JSON object returns empty")
        void emptyObjectReturnsEmpty() {
            assertThat(JsonUtils.parseTargetRef("{}")).isEmpty();
        }
    }

    @Nested
    @DisplayName("safeJsonParse")
    class SafeJsonParse {
        @Test
        @DisplayName("null returns empty map")
        void nullReturnsEmpty() {
            assertThat(JsonUtils.safeJsonParse(null)).isEmpty();
        }

        @Test
        @DisplayName("Map input returned as-is")
        void mapInputReturnedDirectly() {
            Map<String, Object> map = Map.of("key", "value");
            assertThat(JsonUtils.safeJsonParse(map)).isSameAs(map);
        }

        @Test
        @DisplayName("valid JSON string parsed correctly")
        void validJsonStringParsed() {
            String json = "{\"name\": \"test\", \"count\": 42}";
            var result = JsonUtils.safeJsonParse(json);
            assertThat(result).containsEntry("name", "test");
            assertThat(result).containsEntry("count", 42);
        }

        @Test
        @DisplayName("blank string returns empty map")
        void blankStringReturnsEmpty() {
            assertThat(JsonUtils.safeJsonParse("  ")).isEmpty();
        }

        @Test
        @DisplayName("invalid JSON string returns empty map")
        void invalidStringReturnsEmpty() {
            assertThat(JsonUtils.safeJsonParse("not json")).isEmpty();
        }

        @Test
        @DisplayName("non-string non-map returns empty map")
        void nonStringNonMapReturnsEmpty() {
            assertThat(JsonUtils.safeJsonParse(123)).isEmpty();
        }
    }

    @Nested
    @DisplayName("parseJson")
    class ParseJson {
        @Test
        @DisplayName("delegates to safeJsonParse")
        void delegatesToSafeJsonParse() {
            String json = "{\"a\": 1}";
            assertThat(JsonUtils.parseJson(json)).isEqualTo(JsonUtils.safeJsonParse(json));
        }
    }
}
