package com.coremasterkb.serving.operator.core;

/**
 * Declaration of a single operator input or output slot.
 *
 * @param name        slot name, unique within the operator's input (resp. output) set
 * @param type        the slot's {@link SlotType}
 * @param required    for input slots: whether a value must be supplied (via edge or entry binding)
 * @param description human-readable description (surfaced in the operator catalog)
 */
public record SlotDecl(String name, SlotType type, boolean required, String description) {

    /** Convenience for a required input/output slot. */
    public static SlotDecl required(String name, SlotType type, String description) {
        return new SlotDecl(name, type, true, description);
    }

    /** Convenience for an optional input slot. */
    public static SlotDecl optional(String name, SlotType type, String description) {
        return new SlotDecl(name, type, false, description);
    }
}
