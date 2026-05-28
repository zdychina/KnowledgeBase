package com.coremasterkb.serving.domain;

import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Top-level search request accepted by the serving API.
 *
 * @param query           raw user query string (required)
 * @param scope           scoping constraints (e.g. product, version); defaults to empty map
 * @param entities        pre-recognized entities; defaults to empty list
 * @param debug           whether to include debug information in the response
 * @param domain          knowledge domain (e.g. "cloud_core_network")
 * @param channel         release channel (e.g. "prod", "staging"); null means use registry default
 * @param mode            retrieval mode; defaults to "evidence"
 * @param sessionId       optional session identifier for multi-turn context accumulation; null means stateless
 * @param complexityHint  optional override for adaptive routing tier: "simple" | "medium" | "complex";
 *                        null means auto-derive from query understanding
 */
public record SearchRequest(
        String query,
        Map<String, Object> scope,
        List<EntityRef> entities,
        boolean debug,
        String domain,
        String channel,
        String mode,
        String sessionId,
        String complexityHint
) {
    public SearchRequest {
        if (query == null || query.isBlank()) throw new IllegalArgumentException("query_required");
        if (scope == null) scope = Map.of();
        if (entities == null) entities = List.of();
        if (mode == null) mode = "evidence";
        // sessionId / complexityHint: null is valid
        if (complexityHint != null && !Set.of("simple", "medium", "complex").contains(complexityHint)) {
            throw new IllegalArgumentException("complexity_hint_invalid: must be simple | medium | complex");
        }
    }
}
