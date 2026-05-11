package com.coremasterkb.serving.domain;

import java.util.List;
import java.util.Map;

/**
 * Structured query used in the context-assembly phase.
 *
 * @param original    raw user query
 * @param normalized  normalized / cleaned query text
 * @param intent      inferred intent
 * @param entities    recognized entities
 * @param scope       scope constraints
 * @param keywords    extracted keywords
 */
public record ContextQuery(
        String original,
        String normalized,
        String intent,
        List<EntityRef> entities,
        Map<String, Object> scope,
        List<String> keywords
) {
}
