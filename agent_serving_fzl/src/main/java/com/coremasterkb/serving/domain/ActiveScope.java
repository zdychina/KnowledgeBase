package com.coremasterkb.serving.domain;

import java.util.List;
import java.util.Map;

/**
 * Represents the active scoping context for a retrieval operation.
 *
 * @param releaseId           release identifier
 * @param buildId             build identifier
 * @param snapshotIds         snapshot identifiers; defaults to empty list
 * @param documentSnapshotMap mapping from document key to snapshot id; defaults to empty map
 */
public record ActiveScope(
        String releaseId,
        String buildId,
        List<String> snapshotIds,
        Map<String, String> documentSnapshotMap
) {
    public ActiveScope {
        if (snapshotIds == null) snapshotIds = List.of();
        if (documentSnapshotMap == null) documentSnapshotMap = Map.of();
    }
}
