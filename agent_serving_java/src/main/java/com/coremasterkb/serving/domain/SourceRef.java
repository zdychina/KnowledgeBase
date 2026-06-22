package com.coremasterkb.serving.domain;

import java.util.Map;

/**
 * Reference to a source document.
 *
 * @param id           source identifier
 * @param documentKey  document key / path
 * @param title        document title
 * @param relativePath relative path within the knowledge base
 * @param scopeJson    scoping metadata as JSON-compatible map; defaults to empty map
 * @param metadata     additional source metadata; defaults to empty map
 */
public record SourceRef(
        String id,
        String documentKey,
        String title,
        String relativePath,
        Map<String, Object> scopeJson,
        Map<String, Object> metadata
) {
    public SourceRef {
        if (scopeJson == null) scopeJson = Map.of();
        if (metadata == null) metadata = Map.of();
    }
}
