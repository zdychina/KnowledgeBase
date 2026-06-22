package com.coremasterkb.serving.operator.core;

import java.util.List;
import java.util.Optional;

/**
 * Operator metadata, declared by each {@link Operator} and collected by the registry.
 *
 * <p>{@code type} is the stable identifier referenced by paradigm JSON. {@code paramSchemaJson}
 * is a JSON Schema (draft-07) string that the frontend renders into a config form and the
 * compiler validates node params against.</p>
 *
 * @param type            unique operator type id, e.g. {@code "dense_vector"}
 * @param category        UI grouping, e.g. {@code "retrieve"}
 * @param displayName     human label, e.g. {@code "向量检索"}
 * @param description     operator description
 * @param inputSlots      input slot declarations
 * @param outputSlots     output slot declarations
 * @param paramSchemaJson JSON Schema (draft-07) string for node params; {@code {}} if no params
 * @param errorPolicy     how the executor treats a thrown exception from this operator
 */
public record OperatorDef(
        String type,
        String category,
        String displayName,
        String description,
        List<SlotDecl> inputSlots,
        List<SlotDecl> outputSlots,
        String paramSchemaJson,
        ErrorPolicy errorPolicy
) {
    public OperatorDef {
        if (inputSlots == null) inputSlots = List.of();
        if (outputSlots == null) outputSlots = List.of();
        if (paramSchemaJson == null || paramSchemaJson.isBlank()) paramSchemaJson = "{}";
        if (errorPolicy == null) errorPolicy = ErrorPolicy.FAIL_FAST;
    }

    public Optional<SlotDecl> inputSlot(String name) {
        return inputSlots.stream().filter(s -> s.name().equals(name)).findFirst();
    }

    public Optional<SlotDecl> outputSlot(String name) {
        return outputSlots.stream().filter(s -> s.name().equals(name)).findFirst();
    }
}
