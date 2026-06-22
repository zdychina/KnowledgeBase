package com.coremasterkb.serving.domain;

import java.util.List;

/**
 * A decomposed sub-query derived from the original user query.
 *
 * @param text      the sub-query text
 * @param intent    inferred intent; defaults to "general"
 * @param entities  entities recognized within this sub-query; defaults to empty list
 */
public record SubQuery(
        String text,
        String intent,
        List<EntityRef> entities
) {
    public SubQuery {
        if (intent == null) intent = "general";
        if (entities == null) entities = List.of();
    }
}
