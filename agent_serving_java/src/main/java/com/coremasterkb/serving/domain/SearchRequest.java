package com.coremasterkb.serving.domain;

import java.util.List;
import java.util.Map;

/**
 * Top-level search request accepted by the serving API.
 *
 * @param query     raw user query string (required)
 * @param scope     scoping constraints (e.g. product, version); defaults to empty map
 * @param entities  pre-recognized entities; defaults to empty list
 * @param debug     whether to include debug information in the response
 * @param domain    knowledge domain (e.g. "cloud_core_network")
 * @param mode      retrieval mode; defaults to "evidence"
 */
public record SearchRequest(
        String query,
        Map<String, Object> scope,
        List<EntityRef> entities,
        boolean debug,
        String domain,
        String mode
) {
    public SearchRequest {
        if (scope == null) scope = Map.of();
        if (entities == null) entities = List.of();
        if (mode == null) mode = "evidence";
    }
}
