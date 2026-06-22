package com.coremasterkb.serving.entity;

public class AssetRetrievalEmbedding {

    private String id;
    private String retrievalUnitId;
    private String embeddingModel;
    private String embeddingProvider;
    private String textKind;
    private Integer embeddingDim;
    private String embeddingVector;
    private String contentHash;
    private String createdAt;

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }

    public String getRetrievalUnitId() { return retrievalUnitId; }
    public void setRetrievalUnitId(String retrievalUnitId) { this.retrievalUnitId = retrievalUnitId; }

    public String getEmbeddingModel() { return embeddingModel; }
    public void setEmbeddingModel(String embeddingModel) { this.embeddingModel = embeddingModel; }

    public String getEmbeddingProvider() { return embeddingProvider; }
    public void setEmbeddingProvider(String embeddingProvider) { this.embeddingProvider = embeddingProvider; }

    public String getTextKind() { return textKind; }
    public void setTextKind(String textKind) { this.textKind = textKind; }

    public Integer getEmbeddingDim() { return embeddingDim; }
    public void setEmbeddingDim(Integer embeddingDim) { this.embeddingDim = embeddingDim; }

    public String getEmbeddingVector() { return embeddingVector; }
    public void setEmbeddingVector(String embeddingVector) { this.embeddingVector = embeddingVector; }

    public String getContentHash() { return contentHash; }
    public void setContentHash(String contentHash) { this.contentHash = contentHash; }

    public String getCreatedAt() { return createdAt; }
    public void setCreatedAt(String createdAt) { this.createdAt = createdAt; }
}
