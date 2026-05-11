package com.coremasterkb.serving.mapper.result;

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

    public String getSnapshotTitle() { return snapshotTitle; }
    public void setSnapshotTitle(String snapshotTitle) { this.snapshotTitle = snapshotTitle; }

    public String getDocumentId() { return documentId; }
    public void setDocumentId(String documentId) { this.documentId = documentId; }

    public String getDocumentKey() { return documentKey; }
    public void setDocumentKey(String documentKey) { this.documentKey = documentKey; }

    public String getRelativePath() { return relativePath; }
    public void setRelativePath(String relativePath) { this.relativePath = relativePath; }
}
