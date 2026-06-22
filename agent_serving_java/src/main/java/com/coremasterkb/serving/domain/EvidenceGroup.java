package com.coremasterkb.serving.domain;

import java.util.List;

/**
 * Groups context items and relations by document snapshot.
 *
 * @param documentSnapshotId snapshot identifier for the group
 * @param itemIds            context item identifiers in this group; defaults to empty list
 * @param relationIds        relation identifiers in this group; defaults to empty list
 */
public record EvidenceGroup(
        String documentSnapshotId,
        List<String> itemIds,
        List<String> relationIds
) {
    public EvidenceGroup {
        if (itemIds == null) itemIds = List.of();
        if (relationIds == null) relationIds = List.of();
    }
}
