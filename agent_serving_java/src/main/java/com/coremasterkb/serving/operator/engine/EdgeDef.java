package com.coremasterkb.serving.operator.engine;

/**
 * A directed edge connecting an upstream node's output slot to a downstream node's input slot.
 *
 * @param fromNode upstream node id
 * @param fromSlot upstream output slot name
 * @param toNode   downstream node id
 * @param toSlot   downstream input slot name
 */
public record EdgeDef(String fromNode, String fromSlot, String toNode, String toSlot) {

    public String describe() {
        return fromNode + "." + fromSlot + " -> " + toNode + "." + toSlot;
    }
}
