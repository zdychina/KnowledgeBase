package com.coremasterkb.serving.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

@Data
@TableName("asset_retrieval_embeddings")
public class AssetRetrievalEmbedding {

    @TableId(type = IdType.INPUT)
    private String id;
    private String retrievalUnitId;
    private String embeddingModel;
    private String embeddingProvider;
    private String textKind;
    private Integer embeddingDim;
    private String embeddingVector;
    private String contentHash;
    private String createdAt;
}
