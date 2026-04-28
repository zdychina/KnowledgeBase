package com.coremasterkb.serving.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.coremasterkb.serving.entity.AssetRawSegmentRelation;
import com.coremasterkb.serving.mapper.result.NeighborRow;
import com.coremasterkb.serving.mapper.result.RelationRow;
import org.apache.ibatis.annotations.Param;

import java.util.List;

public interface AssetRawSegmentRelationMapper extends BaseMapper<AssetRawSegmentRelation> {

    List<RelationRow> selectRelationsForSegments(
            @Param("segmentIds") List<String> segmentIds,
            @Param("relationTypes") List<String> relationTypes,
            @Param("snapshotIds") List<String> snapshotIds);

    List<NeighborRow> selectNeighbors(
            @Param("segmentIds") List<String> segmentIds,
            @Param("relationTypes") List<String> relationTypes,
            @Param("snapshotIds") List<String> snapshotIds);
}
