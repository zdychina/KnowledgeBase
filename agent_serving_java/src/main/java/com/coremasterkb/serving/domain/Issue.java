package com.coremasterkb.serving.domain;

import java.util.Map;

/**
 * An issue or warning encountered during processing.
 *
 * @param type    issue type (e.g. "warning", "error")
 * @param message human-readable issue description
 * @param detail  additional structured detail; defaults to empty map
 */
public record Issue(
        String type,
        String message,
        Map<String, Object> detail
) {
    public Issue {
        if (detail == null) detail = Map.of();
    }
}
