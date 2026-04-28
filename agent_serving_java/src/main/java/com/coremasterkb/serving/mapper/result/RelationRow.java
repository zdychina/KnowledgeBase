package com.coremasterkb.serving.mapper.result;

import lombok.Data;

@Data
public class RelationRow {
    private String id;
    private String fromSegmentId;
    private String toSegmentId;
    private String relationType;
    private Integer distance;
}
