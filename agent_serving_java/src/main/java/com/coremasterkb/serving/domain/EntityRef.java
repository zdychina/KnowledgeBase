package com.coremasterkb.serving.domain;

/**
 * Reference to a recognized entity extracted from a user query.
 *
 * @param type            entity type (e.g. "product", "network_element"); defaults to ""
 * @param name            raw entity name as it appeared in the query
 * @param normalizedName  canonical / normalized form; defaults to ""
 */
public record EntityRef(
        String type,
        String name,
        String normalizedName
) {
    public EntityRef {
        if (type == null) type = "";
        if (normalizedName == null) normalizedName = "";
    }
}
