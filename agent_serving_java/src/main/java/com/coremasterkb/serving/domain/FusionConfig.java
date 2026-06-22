package com.coremasterkb.serving.domain;

/**
 * Configuration for score fusion across retrieval routes.
 *
 * @param method fusion method; defaults to "weighted_rrf"
 * @param k      RRF k parameter
 */
public record FusionConfig(
        String method,
        int k
) {
    public FusionConfig {
        if (method == null) method = "weighted_rrf";
    }
}
