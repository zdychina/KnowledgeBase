package com.coremasterkb.serving.domain;

/**
 * Configuration for a single retrieval route.
 *
 * @param name    route name (e.g. "lexical_bm25")
 * @param enabled whether this route is active
 * @param weight  fusion weight for this route
 * @param topK    maximum candidates to retrieve from this route
 */
public record RouteConfig(
        String name,
        boolean enabled,
        double weight,
        int topK
) {
}
