package com.coremasterkb.serving.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

@Data
@TableName("asset_publish_releases")
public class AssetPublishRelease {

    @TableId(type = IdType.INPUT)
    private String id;
    private String status;
    private String channel;
    private String buildId;
}
