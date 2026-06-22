package com.coremasterkb.serving.entity;

public class AssetRawSegmentRelation {

    private String id;
    private String sourceSegmentId;
    private String targetSegmentId;
    private String relationType;

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getSourceSegmentId() { return sourceSegmentId; }
    public void setSourceSegmentId(String sourceSegmentId) { this.sourceSegmentId = sourceSegmentId; }

    public String getTargetSegmentId() { return targetSegmentId; }
    public void setTargetSegmentId(String targetSegmentId) { this.targetSegmentId = targetSegmentId; }

    public String getRelationType() { return relationType; }
    public void setRelationType(String relationType) { this.relationType = relationType; }
}
