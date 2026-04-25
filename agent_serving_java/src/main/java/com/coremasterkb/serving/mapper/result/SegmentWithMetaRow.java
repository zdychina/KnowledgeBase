package com.coremasterkb.serving.mapper.result;

import lombok.Data;

@Data
public class SegmentWithMetaRow {
    private String id;
    private String documentSnapshotId;
    private String rawText;
    private String blockType;
    private String semanticRole;
    private String sectionPath;
    private String entityRefsJson;
    private String sourceOffsetsJson;
    private String snapshotTitle;
    private String documentId;
    private String documentKey;
    private String relativePath;
}
