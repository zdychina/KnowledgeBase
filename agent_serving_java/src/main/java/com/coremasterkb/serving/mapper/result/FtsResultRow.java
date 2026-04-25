package com.coremasterkb.serving.mapper.result;

import lombok.Data;

@Data
public class FtsResultRow {
    private String id;
    private String documentSnapshotId;
    private String text;
    private String title;
    private String blockType;
    private String semanticRole;
    private String sourceRefsJson;
    private String facetsJson;
    private String targetType;
    private String targetRefJson;
    private String unitType;
    private String sourceSegmentId;
    private double ftsScore;
}
