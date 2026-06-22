package com.coremasterkb.serving.operator.api;

import com.coremasterkb.serving.operator.api.ParadigmExecutionService.RunArgs;
import com.fasterxml.jackson.databind.JsonNode;

/** Small helpers for reading paradigm request bodies. */
final class ParadigmRequests {

    private ParadigmRequests() {}

    static RunArgs toRunArgs(JsonNode body) {
        return new RunArgs(text(body, "query"), text(body, "domain"), text(body, "channel"),
                body != null && body.hasNonNull("debug") && body.get("debug").asBoolean());
    }

    static String text(JsonNode body, String field) {
        if (body == null) return null;
        JsonNode v = body.get(field);
        return (v != null && v.isTextual() && !v.asText().isBlank()) ? v.asText() : null;
    }

    /** Extract the {@code graph} object from a body as a compact JSON string, or null if absent. */
    static String graphString(JsonNode body) {
        if (body == null) return null;
        JsonNode g = body.get("graph");
        return (g != null && !g.isNull()) ? g.toString() : null;
    }
}
