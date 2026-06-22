package com.coremasterkb.serving.operator.engine;

import java.util.List;
import java.util.Map;

/**
 * A compiled, validated paradigm: the executable DAG form of the paradigm JSON.
 *
 * @param nodes        node id → node definition (insertion-ordered)
 * @param edges        directed edges
 * @param outputNodeId terminal node whose output is the paradigm result
 * @param outputSlot   which output slot of the terminal node to return
 */
public record ParadigmGraph(
        Map<String, NodeDef> nodes,
        List<EdgeDef> edges,
        String outputNodeId,
        String outputSlot
) {
    /** Edges whose target is the given node. */
    public List<EdgeDef> incomingEdges(String nodeId) {
        return edges.stream().filter(e -> e.toNode().equals(nodeId)).toList();
    }

    /** Edges feeding the given (node, inputSlot). */
    public List<EdgeDef> incomingEdges(String nodeId, String toSlot) {
        return edges.stream()
                .filter(e -> e.toNode().equals(nodeId) && e.toSlot().equals(toSlot))
                .toList();
    }
}
