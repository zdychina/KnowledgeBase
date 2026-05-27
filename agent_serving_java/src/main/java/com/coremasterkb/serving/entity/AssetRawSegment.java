package com.coremasterkb.serving.entity;

public class AssetRawSegment {

    private String id;
    private String documentSnapshotId;
    private String rawText;
    private String blockType;
    private String semanticRole;
    private String sectionPath;
    private String entityRefsJson;
    private String sourceOffsetsJson;

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getDocumentSnapshotId() { return documentSnapshotId; }
    public void setDocumentSnapshotId(String documentSnapshotId) { this.documentSnapshotId = documentSnapshotId; }

    public String getRawText() { return rawText; }
    public void setRawText(String rawText) { this.rawText = rawText; }

    public String getBlockType() { return blockType; }
    public void setBlockType(String blockType) { this.blockType = blockType; }

    public String getSemanticRole() { return semanticRole; }
    public void setSemanticRole(String semanticRole) { this.semanticRole = semanticRole; }

    public String getSectionPath() { return sectionPath; }
    public void setSectionPath(String sectionPath) { this.sectionPath = sectionPath; }

    public String getEntityRefsJson() { return entityRefsJson; }
    public void setEntityRefsJson(String entityRefsJson) { this.entityRefsJson = entityRefsJson; }

    public String getSourceOffsetsJson() { return sourceOffsetsJson; }
    public void setSourceOffsetsJson(String sourceOffsetsJson) { this.sourceOffsetsJson = sourceOffsetsJson; }
}
