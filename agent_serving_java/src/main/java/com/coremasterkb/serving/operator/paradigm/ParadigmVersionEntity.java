package com.coremasterkb.serving.operator.paradigm;

/** Row of {@code operator_paradigm_version}: an immutable published snapshot of a paradigm graph. */
public class ParadigmVersionEntity {

    private String id;
    private String paradigmId;
    private int version;
    private String graphJson;   // JSONB stored/read as raw JSON text
    private String schemaVersion;
    private String createdAt;
    private String createdBy;

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getParadigmId() { return paradigmId; }
    public void setParadigmId(String paradigmId) { this.paradigmId = paradigmId; }

    public int getVersion() { return version; }
    public void setVersion(int version) { this.version = version; }

    public String getGraphJson() { return graphJson; }
    public void setGraphJson(String graphJson) { this.graphJson = graphJson; }

    public String getSchemaVersion() { return schemaVersion; }
    public void setSchemaVersion(String schemaVersion) { this.schemaVersion = schemaVersion; }

    public String getCreatedAt() { return createdAt; }
    public void setCreatedAt(String createdAt) { this.createdAt = createdAt; }

    public String getCreatedBy() { return createdBy; }
    public void setCreatedBy(String createdBy) { this.createdBy = createdBy; }
}
