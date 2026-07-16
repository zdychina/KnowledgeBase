package com.coremasterkb.serving.operator.engine;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * A single node in a paradigm graph.
 *
 * @param nodeId       unique node id on the canvas, e.g. {@code "dv1"}
 * @param operatorType the operator type this node instantiates, e.g. {@code "dense_vector"}
 * @param params       this node's param values (an object node; may be empty)
 */
public record NodeDef(String nodeId, String operatorType, JsonNode params) {}
