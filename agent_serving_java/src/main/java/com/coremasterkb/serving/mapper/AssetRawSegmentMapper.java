package com.coremasterkb.serving.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.coremasterkb.serving.entity.AssetRawSegment;
import com.coremasterkb.serving.mapper.result.SegmentWithMetaRow;
import org.apache.ibatis.annotations.Param;

import java.util.List;

public interface AssetRawSegmentMapper extends BaseMapper<AssetRawSegment> {

    List<SegmentWithMetaRow> selectWithMeta(
            @Param("segmentIds") List<String> segmentIds,
            @Param("snapshotIds") List<String> snapshotIds);
}
