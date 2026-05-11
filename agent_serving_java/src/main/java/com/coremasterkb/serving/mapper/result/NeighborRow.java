package com.coremasterkb.serving.mapper.result;

public class NeighborRow {
    private String fromId;
    private String neighborId;
    private String relationType;

    public String getFromId() { return fromId; }
    public void setFromId(String fromId) { this.fromId = fromId; }

    public String getNeighborId() { return neighborId; }
    public void setNeighborId(String neighborId) { this.neighborId = neighborId; }

    public String getRelationType() { return relationType; }
    public void setRelationType(String relationType) { this.relationType = relationType; }
}
