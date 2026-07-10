package com.coremasterkb.serving.mapper.result;

/**
 * One retrieval-unit row surfaced by ontology-graph recall.
 *
 * <p>Carries the standard unit fields (mirroring {@link FtsResultRow}) plus the two
 * graph-specific quantities used for scoring: {@code hop} (shortest hop distance from a
 * linked seed entity to the entity this unit is evidence for) and {@code conf} (best
 * path confidence = product of edge confidences along that path).</p>
 */
public class OntologyGraphRow {
    private String id;                 // retrieval_unit id (candidate key)
    private String text;
    private String title;
    private String documentSnapshotId;
    private String blockType;
    private String semanticRole;
    private String unitType;
    private String sourceSegmentId;
    private int hop;                   // 0 = seed entity's own evidence
    private double conf;               // path confidence in [0,1]

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getText() { return text; }
    public void setText(String text) { this.text = text; }

    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }

    public String getDocumentSnapshotId() { return documentSnapshotId; }
    public void setDocumentSnapshotId(String documentSnapshotId) { this.documentSnapshotId = documentSnapshotId; }

    public String getBlockType() { return blockType; }
    public void setBlockType(String blockType) { this.blockType = blockType; }

    public String getSemanticRole() { return semanticRole; }
    public void setSemanticRole(String semanticRole) { this.semanticRole = semanticRole; }

    public String getUnitType() { return unitType; }
    public void setUnitType(String unitType) { this.unitType = unitType; }

    public String getSourceSegmentId() { return sourceSegmentId; }
    public void setSourceSegmentId(String sourceSegmentId) { this.sourceSegmentId = sourceSegmentId; }

    public int getHop() { return hop; }
    public void setHop(int hop) { this.hop = hop; }

    public double getConf() { return conf; }
    public void setConf(double conf) { this.conf = conf; }
}
