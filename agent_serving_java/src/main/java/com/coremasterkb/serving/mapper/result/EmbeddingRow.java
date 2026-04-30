package com.coremasterkb.serving.mapper.result;

import lombok.Data;

/**
 * Result row for dense vector retrieval:
 * JOIN asset_retrieval_embeddings + asset_retrieval_units.
 */
@Data
public class EmbeddingRow {

    private String retrievalUnitId;
    private String embeddingVector;     // serialized JSON float array
    private int    embeddingDim;

    // Fields from asset_retrieval_units (needed to build RetrievalCandidate)
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
}
