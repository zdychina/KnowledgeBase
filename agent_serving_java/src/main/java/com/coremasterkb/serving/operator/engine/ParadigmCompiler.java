package com.coremasterkb.serving.operator.engine;

import com.coremasterkb.serving.operator.core.OperatorDef;
import com.coremasterkb.serving.operator.core.SlotDecl;
import com.coremasterkb.serving.operator.core.SlotType;
import com.coremasterkb.serving.operator.core.exceptions.ParadigmCompileException;
import com.coremasterkb.serving.operator.registry.OperatorRegistry;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SpecVersion;
import com.networknt.schema.ValidationMessage;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Compiles paradigm JSON (PRD §9) into a validated {@link ParadigmGraph}.
 *
 * <p>Performs the seven compile-time checks (PRD §8.2) without executing any operator:
 * node existence, param schema, edge slot-type compatibility, slot occupancy, acyclicity,
 * terminal-output validity, and required-input completeness. All errors are collected and
 * thrown together as a {@link ParadigmCompileException}.</p>
 */
@Component
public class ParadigmCompiler {

    /**
     * Implicit entry slots bound from the HTTP request (PRD §8.4). Only {@code query} is actually
     * supplied by the executor's entry inputs, so {@code scope} is intentionally NOT here: a
     * required {@code scope} input must be wired from a {@code scope_resolve} node — otherwise the
     * graph would compile "valid" yet run with an unbound (null) scope and silently retrieve nothing.
     */
    static final Map<String, SlotType> ENTRY_SLOTS = Map.of(
            "query", SlotType.STRING);

    private final OperatorRegistry registry;
    private final ObjectMapper mapper = new ObjectMapper();
    private final JsonSchemaFactory schemaFactory = JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V7);
    /** Parsed JSON Schema per operator type — paramSchemaJson is a static constant, so parse once. */
    private final Map<String, JsonSchema> schemaCache = new java.util.concurrent.ConcurrentHashMap<>();

    public ParadigmCompiler(OperatorRegistry registry) {
        this.registry = registry;
    }

    /** Compile and validate; throws {@link ParadigmCompileException} on any error. */
    public ParadigmGraph compile(JsonNode paradigmJson) {
        List<CompileError> errors = new ArrayList<>();

        ParadigmGraph graph = parse(paradigmJson, errors);
        if (graph == null) {
            throw new ParadigmCompileException(errors);
        }

        checkNodesAndParams(graph, errors);
        checkEdges(graph, errors);
        checkSlotOccupancy(graph, errors);
        checkAcyclic(graph, errors);
        checkOutput(graph, errors);
        checkRequiredInputs(graph, errors);

        if (!errors.isEmpty()) {
            throw new ParadigmCompileException(errors);
        }
        return graph;
    }

    /** Validate only, returning the error list (never throws). For the {@code /validate} endpoint. */
    public List<CompileError> validate(JsonNode paradigmJson) {
        try {
            compile(paradigmJson);
            return List.of();
        } catch (ParadigmCompileException e) {
            return e.errors();
        }
    }

    // -------------------------------------------------------------------------
    // Parsing
    // -------------------------------------------------------------------------

    private ParadigmGraph parse(JsonNode root, List<CompileError> errors) {
        if (root == null || !root.isObject()) {
            errors.add(CompileError.general("malformed", "paradigm JSON must be an object"));
            return null;
        }
        JsonNode nodesNode = root.get("nodes");
        JsonNode edgesNode = root.get("edges");
        JsonNode outputNode = root.get("output");

        if (nodesNode == null || !nodesNode.isArray() || nodesNode.isEmpty()) {
            errors.add(CompileError.general("malformed", "'nodes' must be a non-empty array"));
            return null;
        }

        Map<String, NodeDef> nodes = new LinkedHashMap<>();
        for (JsonNode n : nodesNode) {
            String nodeId = text(n, "nodeId");
            String opType = text(n, "operatorType");
            if (nodeId == null || nodeId.isBlank()) {
                errors.add(CompileError.general("malformed", "a node is missing 'nodeId'"));
                continue;
            }
            if (opType == null || opType.isBlank()) {
                errors.add(CompileError.node("malformed", nodeId, "node missing 'operatorType'"));
                continue;
            }
            if (nodes.containsKey(nodeId)) {
                errors.add(CompileError.node("malformed", nodeId, "duplicate nodeId"));
                continue;
            }
            JsonNode params = n.get("params");
            if (params == null || !params.isObject()) {
                params = JsonNodeFactory.instance.objectNode();
            }
            nodes.put(nodeId, new NodeDef(nodeId, opType, params));
        }

        List<EdgeDef> edges = new ArrayList<>();
        if (edgesNode != null && edgesNode.isArray()) {
            for (JsonNode e : edgesNode) {
                String fromNode = text(e, "fromNode");
                String fromSlot = text(e, "fromSlot");
                String toNode = text(e, "toNode");
                String toSlot = text(e, "toSlot");
                if (fromNode == null || fromSlot == null || toNode == null || toSlot == null) {
                    errors.add(CompileError.general("malformed", "an edge is missing fromNode/fromSlot/toNode/toSlot"));
                    continue;
                }
                edges.add(new EdgeDef(fromNode, fromSlot, toNode, toSlot));
            }
        }

        if (outputNode == null || !outputNode.isObject()) {
            errors.add(CompileError.general("malformed", "'output' must specify {nodeId, slot}"));
            return null;
        }
        String outNodeId = text(outputNode, "nodeId");
        String outSlot = text(outputNode, "slot");
        if (outNodeId == null || outSlot == null) {
            errors.add(CompileError.general("malformed", "'output' must specify both 'nodeId' and 'slot'"));
            return null;
        }

        if (nodes.isEmpty()) {
            return null;
        }
        return new ParadigmGraph(nodes, edges, outNodeId, outSlot);
    }

    // -------------------------------------------------------------------------
    // Checks 1 & 2: node existence + param schema
    // -------------------------------------------------------------------------

    private void checkNodesAndParams(ParadigmGraph graph, List<CompileError> errors) {
        for (NodeDef node : graph.nodes().values()) {
            if (!registry.contains(node.operatorType())) {
                errors.add(CompileError.node("unknown_operator", node.nodeId(),
                        "unknown operator type '" + node.operatorType() + "'"));
                continue;
            }
            OperatorDef def = registry.def(node.operatorType());
            validateParams(node, def, errors);
        }
    }

    private void validateParams(NodeDef node, OperatorDef def, List<CompileError> errors) {
        try {
            JsonSchema schema = schemaCache.computeIfAbsent(def.type(),
                    t -> schemaFactory.getSchema(parseSchema(def.paramSchemaJson())));
            Set<ValidationMessage> messages = schema.validate(node.params());
            for (ValidationMessage m : messages) {
                errors.add(CompileError.node("param_schema", node.nodeId(),
                        "param validation: " + m.getMessage()));
            }
        } catch (Exception e) {
            errors.add(CompileError.node("param_schema", node.nodeId(),
                    "param schema check failed: " + e.getMessage()));
        }
    }

    // -------------------------------------------------------------------------
    // Check 3: edge slot-type compatibility
    // -------------------------------------------------------------------------

    private void checkEdges(ParadigmGraph graph, List<CompileError> errors) {
        for (EdgeDef e : graph.edges()) {
            NodeDef from = graph.nodes().get(e.fromNode());
            NodeDef to = graph.nodes().get(e.toNode());
            if (from == null) {
                errors.add(CompileError.edge("malformed", e, "fromNode '" + e.fromNode() + "' does not exist"));
                continue;
            }
            if (to == null) {
                errors.add(CompileError.edge("malformed", e, "toNode '" + e.toNode() + "' does not exist"));
                continue;
            }
            OperatorDef fromDef = registry.def(from.operatorType());
            OperatorDef toDef = registry.def(to.operatorType());
            if (fromDef == null || toDef == null) {
                continue; // unknown operator already reported
            }
            SlotDecl fromSlot = fromDef.outputSlot(e.fromSlot()).orElse(null);
            SlotDecl toSlot = toDef.inputSlot(e.toSlot()).orElse(null);
            if (fromSlot == null) {
                errors.add(CompileError.edge("malformed", e,
                        "operator '" + fromDef.type() + "' has no output slot '" + e.fromSlot() + "'"));
                continue;
            }
            if (toSlot == null) {
                errors.add(CompileError.edge("malformed", e,
                        "operator '" + toDef.type() + "' has no input slot '" + e.toSlot() + "'"));
                continue;
            }
            if (!SlotType.isAssignable(fromSlot.type(), toSlot.type())) {
                errors.add(CompileError.edge("type_mismatch", e,
                        "type " + fromSlot.type() + " cannot feed " + toSlot.type()));
            }
        }
    }

    // -------------------------------------------------------------------------
    // Check 4: slot occupancy (non-variadic inputs take at most one incoming edge)
    // -------------------------------------------------------------------------

    private void checkSlotOccupancy(ParadigmGraph graph, List<CompileError> errors) {
        for (NodeDef node : graph.nodes().values()) {
            OperatorDef def = registry.def(node.operatorType());
            if (def == null) continue;
            for (SlotDecl slot : def.inputSlots()) {
                if (slot.type() == SlotType.CANDIDATE_LIST_MULTI) {
                    continue; // variadic: many inputs allowed
                }
                long count = graph.incomingEdges(node.nodeId(), slot.name()).size();
                if (count > 1) {
                    errors.add(CompileError.node("slot_occupancy", node.nodeId(),
                            "input slot '" + slot.name() + "' has " + count
                                    + " incoming edges but is not variadic"));
                }
            }
        }
    }

    // -------------------------------------------------------------------------
    // Check 5: acyclicity (Kahn topological sort)
    // -------------------------------------------------------------------------

    private void checkAcyclic(ParadigmGraph graph, List<CompileError> errors) {
        Map<String, Integer> indegree = new HashMap<>();
        for (String id : graph.nodes().keySet()) {
            indegree.put(id, 0);
        }
        Map<String, List<String>> adj = new HashMap<>();
        for (EdgeDef e : graph.edges()) {
            if (!graph.nodes().containsKey(e.fromNode()) || !graph.nodes().containsKey(e.toNode())) {
                continue;
            }
            adj.computeIfAbsent(e.fromNode(), k -> new ArrayList<>()).add(e.toNode());
            indegree.merge(e.toNode(), 1, Integer::sum);
        }
        List<String> queue = new ArrayList<>();
        indegree.forEach((id, deg) -> { if (deg == 0) queue.add(id); });
        int visited = 0;
        while (!queue.isEmpty()) {
            String n = queue.remove(queue.size() - 1);
            visited++;
            for (String next : adj.getOrDefault(n, List.of())) {
                if (indegree.merge(next, -1, Integer::sum) == 0) {
                    queue.add(next);
                }
            }
        }
        if (visited < graph.nodes().size()) {
            errors.add(CompileError.general("cycle", "paradigm graph contains a cycle"));
        }
    }

    // -------------------------------------------------------------------------
    // Check 6: terminal output validity
    // -------------------------------------------------------------------------

    private void checkOutput(ParadigmGraph graph, List<CompileError> errors) {
        NodeDef outNode = graph.nodes().get(graph.outputNodeId());
        if (outNode == null) {
            errors.add(CompileError.general("bad_output",
                    "output nodeId '" + graph.outputNodeId() + "' does not exist"));
            return;
        }
        OperatorDef def = registry.def(outNode.operatorType());
        if (def == null) {
            return; // unknown operator already reported
        }
        if (def.outputSlot(graph.outputSlot()).isEmpty()) {
            errors.add(CompileError.general("bad_output",
                    "output node '" + graph.outputNodeId() + "' (" + def.type()
                            + ") has no output slot '" + graph.outputSlot() + "'"));
        }
    }

    // -------------------------------------------------------------------------
    // Check 7: required-input completeness (edge or entry-slot binding)
    // -------------------------------------------------------------------------

    private void checkRequiredInputs(ParadigmGraph graph, List<CompileError> errors) {
        for (NodeDef node : graph.nodes().values()) {
            OperatorDef def = registry.def(node.operatorType());
            if (def == null) continue;
            for (SlotDecl slot : def.inputSlots()) {
                if (!slot.required()) continue;
                boolean hasEdge = !graph.incomingEdges(node.nodeId(), slot.name()).isEmpty();
                if (hasEdge) continue;
                SlotType entryType = ENTRY_SLOTS.get(slot.name());
                boolean entrySatisfies = entryType != null && SlotType.isAssignable(entryType, slot.type());
                if (!entrySatisfies) {
                    errors.add(CompileError.node("missing_required_input", node.nodeId(),
                            "required input slot '" + slot.name() + "' (" + slot.type()
                                    + ") has no incoming edge and no matching entry input"));
                }
            }
        }
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    private static String text(JsonNode node, String field) {
        if (node == null) return null;
        JsonNode v = node.get(field);
        return (v != null && v.isTextual()) ? v.asText() : null;
    }

    /** Parse a schema JSON string; wraps the checked exception so it can be used in computeIfAbsent. */
    private JsonNode parseSchema(String json) {
        try {
            return mapper.readTree(json);
        } catch (Exception e) {
            throw new RuntimeException("invalid operator paramSchemaJson: " + e.getMessage(), e);
        }
    }
}
