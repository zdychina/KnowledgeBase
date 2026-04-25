package com.coremasterkb.serving.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

@Data
@TableName("asset_documents")
public class AssetDocument {

    @TableId(type = IdType.INPUT)
    private String id;
    private String documentKey;
}
