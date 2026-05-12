package com.coremasterkb.serving.mapper.result;

public class RelationRow {
    private String id;
    private String fromSegmentId;
    private String toSegmentId;
    private String relationType;
    private Integer distance;

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getFromSegmentId() { return fromSegmentId; }
    public void setFromSegmentId(String fromSegmentId) { this.fromSegmentId = fromSegmentId; }

    public String getToSegmentId() { return toSegmentId; }
    public void setToSegmentId(String toSegmentId) { this.toSegmentId = toSegmentId; }

    public String getRelationType() { return relationType; }
    public void setRelationType(String relationType) { this.relationType = relationType; }

    public Integer getDistance() { return distance; }
    public void setDistance(Integer distance) { this.distance = distance; }
}
