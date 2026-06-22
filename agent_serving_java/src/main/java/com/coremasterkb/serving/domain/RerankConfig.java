package com.coremasterkb.serving.domain;

/**
 * Configuration for the reranking stage.
 *
 * @param method    primary reranking method; defaults to "score"
 * @param fallback  fallback method if primary fails; defaults to "score"
 */
public record RerankConfig(
        String method,
        String fallback
) {
    public RerankConfig {
        if (method == null) method = "score";
        if (fallback == null) fallback = "score";
    }
}
