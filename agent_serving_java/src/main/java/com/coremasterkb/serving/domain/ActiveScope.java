package com.coremasterkb.serving.domain;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public record ActiveScope(
        @JsonProperty("release_id") String releaseId,
        @JsonProperty("build_id") String buildId,
        @JsonProperty("snapshot_ids") List<String> snapshotIds,
        @JsonProperty("document_snapshot_map") Map<String, String> documentSnapshotMap
) {
    public ActiveScope {
        if (snapshotIds == null) snapshotIds = new ArrayList<>();
        if (documentSnapshotMap == null) documentSnapshotMap = new HashMap<>();
    }
}
