package com.coremasterkb.serving.operator.core;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Thin, null-safe accessor over a node's params {@link JsonNode} (an object node).
 *
 * <p>Operators read params through typed getters with defaults. Schema validation has already
 * happened at compile time, so getters here are lenient and never throw on missing keys.</p>
 */
public final class Params {

    private static final JsonNode EMPTY = JsonNodeFactory.instance.objectNode();

    private final JsonNode node;

    public Params(JsonNode node) {
        this.node = (node != null && node.isObject()) ? node : EMPTY;
    }

    public static Params empty() {
        return new Params(EMPTY);
    }

    public boolean has(String key) {
        return node.hasNonNull(key);
    }

    public String getString(String key, String def) {
        JsonNode v = node.get(key);
        return (v != null && v.isTextual()) ? v.asText() : def;
    }

    public int getInt(String key, int def) {
        JsonNode v = node.get(key);
        return (v != null && v.isNumber()) ? v.asInt() : def;
    }

    public double getDouble(String key, double def) {
        JsonNode v = node.get(key);
        return (v != null && v.isNumber()) ? v.asDouble() : def;
    }

    public boolean getBool(String key, boolean def) {
        JsonNode v = node.get(key);
        return (v != null && v.isBoolean()) ? v.asBoolean() : def;
    }

    /** Returns the string elements of an array param, or an empty list if absent/not an array. */
    public List<String> getStringList(String key) {
        JsonNode v = node.get(key);
        List<String> out = new ArrayList<>();
        if (v != null && v.isArray()) {
            v.forEach(e -> {
                if (e != null && !e.isNull()) out.add(e.asText());
            });
        }
        return out;
    }

    /** Returns a {key:double} map for an object param (e.g. fusion weights), or an empty map. */
    public Map<String, Double> getDoubleMap(String key) {
        JsonNode v = node.get(key);
        Map<String, Double> out = new LinkedHashMap<>();
        if (v != null && v.isObject()) {
            v.fields().forEachRemaining(e -> {
                if (e.getValue() != null && e.getValue().isNumber()) {
                    out.put(e.getKey(), e.getValue().asDouble());
                }
            });
        }
        return out;
    }

    public JsonNode raw() {
        return node;
    }
}
