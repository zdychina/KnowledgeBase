package com.coremasterkb.serving.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

@Data
@TableName("asset_build_document_snapshots")
public class AssetBuildDocumentSnapshot {

    @TableId(type = IdType.INPUT)
    private String documentSnapshotId;
    private String buildId;
    private String documentId;
    private String selectionStatus;
}
