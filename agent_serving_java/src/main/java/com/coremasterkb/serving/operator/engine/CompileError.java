package com.coremasterkb.serving.operator.engine;

/**
 * A structured compile-time error, returned to the frontend so it can highlight the
 * offending node or edge.
 *
 * @param kind    error category, e.g. {@code unknown_operator}, {@code type_mismatch},
 *                {@code cycle}, {@code missing_required_input}, {@code param_schema},
 *                {@code slot_occupancy}, {@code bad_output}, {@code malformed}
 * @param nodeId  related node id (nullable)
 * @param edge    related edge description (nullable)
 * @param message human-readable explanation
 */
public record CompileError(String kind, String nodeId, String edge, String message) {

    public static CompileError node(String kind, String nodeId, String message) {
        return new CompileError(kind, nodeId, null, message);
    }

    public static CompileError edge(String kind, EdgeDef edge, String message) {
        return new CompileError(kind, null, edge.describe(), message);
    }

    public static CompileError general(String kind, String message) {
        return new CompileError(kind, null, null, message);
    }
}
