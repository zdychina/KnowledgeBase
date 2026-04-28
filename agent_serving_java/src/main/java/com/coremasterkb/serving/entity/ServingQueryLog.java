package com.coremasterkb.serving.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

@Data
@TableName("serving_query_logs")
public class ServingQueryLog {

    @TableId(type = IdType.INPUT)
    private String id;

    // 原始输入
    private String queryText;
    private String channel;

    // 查询解析结果
    private String intent;
    private String normalizerSource;
    private String keywordsJson;
    private String entitiesJson;
    private String scopeJson;

    // 命中的知识库版本
    private String releaseId;
    private String buildId;
    private Integer snapshotCount;

    // 响应摘要
    private Integer resultItemCount;
    private Integer resultSeedCount;
    private String resultHasResult;
    private String resultIssuesJson;

    // 返回结果详情
    private String resultItemsJson;
    private String resultSourcesJson;
    private String resultRelationsJson;

    // 性能
    private Integer durationMs;

    // 元数据
    private String queriedAt;
    private String metadataJson;
}
