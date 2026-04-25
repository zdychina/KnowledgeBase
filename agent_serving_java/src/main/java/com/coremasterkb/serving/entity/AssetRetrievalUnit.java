package com.coremasterkb.serving.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

@Data
@TableName("asset_retrieval_units")
public class AssetRetrievalUnit {

    @TableId(type = IdType.INPUT)
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
}
