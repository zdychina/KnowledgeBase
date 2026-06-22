package com.coremasterkb.serving.util;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;

/**
 * JSON utility methods translated from schemas/json_utils.py.
 */
public final class JsonUtils {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private JsonUtils() {}

    /**
     * parseSourceRefs -- format: {"raw_segment_ids": ["id1", "id2", ...]}
     */
    public static List<String> parseSourceRefs(String sourceRefsJson) {
        if (sourceRefsJson == null || sourceRefsJson.isBlank()) {
            return Collections.emptyList();
        }
        try {
            Map<String, Object> data = MAPPER.readValue(sourceRefsJson, new TypeReference<>() {});
            Object ids = data.get("raw_segment_ids");
            if (ids instanceof List<?> list) {
                List<String> result = new ArrayList<>();
                for (Object v : list) {
                    if (v instanceof String s) {
                        result.add(s);
                    }
                }
                return result;
            }
            return Collections.emptyList();
        } catch (Exception e) {
            return Collections.emptyList();
        }
    }

    /**
     * parseTargetRef -- format: {"raw_segment_id": "id"} or {"raw_segment_ids": ["id1", ...]}
     */
    public static List<String> parseTargetRef(String targetRefJson) {
        if (targetRefJson == null || targetRefJson.isBlank()) {
            return Collections.emptyList();
        }
        try {
            Map<String, Object> data = MAPPER.readValue(targetRefJson, new TypeReference<>() {});
            if (data.containsKey("raw_segment_id")) {
                Object v = data.get("raw_segment_id");
                if (v instanceof String s) {
                    return List.of(s);
                }
                return Collections.emptyList();
            }
            if (data.containsKey("raw_segment_ids")) {
                Object ids = data.get("raw_segment_ids");
                if (ids instanceof List<?> list) {
                    List<String> result = new ArrayList<>();
                    for (Object v : list) {
                        if (v instanceof String s) {
                            result.add(s);
                        }
                    }
                    return result;
                }
            }
            return Collections.emptyList();
        } catch (Exception e) {
            return Collections.emptyList();
        }
    }

    /**
     * safeJsonParse -- parse raw string to Map; return empty map on failure or if already a Map.
     */
    @SuppressWarnings("unchecked")
    public static Map<String, Object> safeJsonParse(Object raw) {
        if (raw == null) {
            return Collections.emptyMap();
        }
        if (raw instanceof Map<?, ?> m) {
            return (Map<String, Object>) m;
        }
        if (raw instanceof String s) {
            if (s.isBlank()) return Collections.emptyMap();
            try {
                return MAPPER.readValue(s, new TypeReference<>() {});
            } catch (Exception e) {
                return Collections.emptyMap();
            }
        }
        return Collections.emptyMap();
    }

    /**
     * Parse a JSON string into a generic Map (null-safe).
     */
    public static Map<String, Object> parseJson(String json) {
        return safeJsonParse(json);
    }

    /** Shared ObjectMapper instance for use by other components. */
    public static ObjectMapper mapper() {
        return MAPPER;
    }
}
