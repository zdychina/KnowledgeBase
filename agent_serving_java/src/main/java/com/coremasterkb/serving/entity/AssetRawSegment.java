package com.coremasterkb.serving.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

@Data
@TableName("asset_raw_segments")
public class AssetRawSegment {

    @TableId(type = IdType.INPUT)
    private String id;
    private String documentSnapshotId;
    private String rawText;
    private String blockType;
    private String semanticRole;
    private String sectionPath;
    private String entityRefsJson;
    private String sourceOffsetsJson;
}
