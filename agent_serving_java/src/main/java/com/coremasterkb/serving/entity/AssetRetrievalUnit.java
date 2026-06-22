package com.coremasterkb.serving.entity;

public class AssetRetrievalUnit {

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

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getDocumentSnapshotId() { return documentSnapshotId; }
    public void setDocumentSnapshotId(String documentSnapshotId) { this.documentSnapshotId = documentSnapshotId; }

    public String getText() { return text; }
    public void setText(String text) { this.text = text; }

    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }

    public String getBlockType() { return blockType; }
    public void setBlockType(String blockType) { this.blockType = blockType; }

    public String getSemanticRole() { return semanticRole; }
    public void setSemanticRole(String semanticRole) { this.semanticRole = semanticRole; }

    public String getSourceRefsJson() { return sourceRefsJson; }
    public void setSourceRefsJson(String sourceRefsJson) { this.sourceRefsJson = sourceRefsJson; }

    public String getFacetsJson() { return facetsJson; }
    public void setFacetsJson(String facetsJson) { this.facetsJson = facetsJson; }

    public String getTargetType() { return targetType; }
    public void setTargetType(String targetType) { this.targetType = targetType; }

    public String getTargetRefJson() { return targetRefJson; }
    public void setTargetRefJson(String targetRefJson) { this.targetRefJson = targetRefJson; }

    public String getUnitType() { return unitType; }
    public void setUnitType(String unitType) { this.unitType = unitType; }

    public String getSourceSegmentId() { return sourceSegmentId; }
    public void setSourceSegmentId(String sourceSegmentId) { this.sourceSegmentId = sourceSegmentId; }
}
