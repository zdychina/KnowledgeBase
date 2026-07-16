package com.coremasterkb.serving.operator.engine;

import com.coremasterkb.serving.operator.core.OperatorDef;
import com.coremasterkb.serving.operator.core.SlotDecl;
import com.coremasterkb.serving.operator.core.SlotType;
import com.coremasterkb.serving.operator.core.SlotValues;
import com.coremasterkb.serving.operator.core.exceptions.SlotTypeMismatchException;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Binds a node's input slots from upstream outputs / entry inputs, and validates a node's
 * output slot types at runtime. Stateless helper used by {@link ParadigmExecutor}.
 */
final class SlotBinder {

    private SlotBinder() {}

    /**
     * Gather the input {@link SlotValues} for a node:
     * <ul>
     *   <li>variadic ({@code CANDIDATE_LIST_MULTI}) inputs merge all upstream candidate lists;</li>
     *   <li>a single incoming edge binds that upstream output;</li>
     *   <li>no incoming edge falls back to a matching entry input (e.g. {@code query}, {@code scope}).</li>
     * </ul>
     */
    static SlotValues bindInputs(
            NodeDef node,
            OperatorDef def,
            ParadigmGraph graph,
            Map<String, SlotValues> results,
            Map<String, Object> entryInputs) {

        SlotValues inputs = new SlotValues();

        for (SlotDecl slot : def.inputSlots()) {
            List<EdgeDef> incoming = graph.incomingEdges(node.nodeId(), slot.name());

            if (slot.type() == SlotType.CANDIDATE_LIST_MULTI) {
                List<Object> merged = new ArrayList<>();
                for (EdgeDef e : incoming) {
                    SlotValues up = results.get(e.fromNode());
                    if (up != null) {
                        merged.addAll(up.getCandidates(e.fromSlot()));
                    }
                }
                inputs.put(slot.name(), merged);
                continue;
            }

            if (incoming.size() == 1) {
                EdgeDef e = incoming.get(0);
                SlotValues up = results.get(e.fromNode());
                inputs.put(slot.name(), up != null ? up.get(e.fromSlot()) : null);
            } else if (incoming.isEmpty() && entryInputs.containsKey(slot.name())) {
                inputs.put(slot.name(), entryInputs.get(slot.name()));
            }
            // else: leave unbound; compile-time required-input check already guaranteed validity,
            // and the operator sees a missing optional slot.
        }
        return inputs;
    }

    /** Runtime type check: every present output value must match its declared slot type. */
    static void validateOutputs(OperatorDef def, SlotValues outputs) {
        if (outputs == null) {
            return;
        }
        for (SlotDecl slot : def.outputSlots()) {
            if (outputs.has(slot.name())) {
                Object v = outputs.get(slot.name());
                if (!slot.type().matches(v)) {
                    throw new SlotTypeMismatchException(
                            "operator '" + def.type() + "' output slot '" + slot.name()
                                    + "' expected " + slot.type()
                                    + " but produced " + (v == null ? "null" : v.getClass().getSimpleName()));
                }
            }
        }
    }
}
