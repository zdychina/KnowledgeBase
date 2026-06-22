package com.coremasterkb.serving.domain;

/**
 * A relation between two context items.
 *
 * @param id           relation identifier
 * @param fromId       source item identifier
 * @param toId         target item identifier
 * @param relationType type of relation (e.g. "same_section", "elaborates")
 * @param distance     hop distance from seed (null if not applicable)
 */
public record ContextRelation(
        String id,
        String fromId,
        String toId,
        String relationType,
        Integer distance
) {
}
