package com.coremasterkb.serving.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

@Data
@TableName("asset_raw_segment_relations")
public class AssetRawSegmentRelation {

    @TableId(type = IdType.INPUT)
    private String id;
    private String sourceSegmentId;
    private String targetSegmentId;
    private String relationType;
}
