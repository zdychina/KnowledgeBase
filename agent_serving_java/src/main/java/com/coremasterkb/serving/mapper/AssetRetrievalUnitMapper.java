package com.coremasterkb.serving.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.coremasterkb.serving.entity.AssetRetrievalUnit;
import com.coremasterkb.serving.mapper.result.FtsResultRow;
import org.apache.ibatis.annotations.Param;

import java.util.List;

public interface AssetRetrievalUnitMapper extends BaseMapper<AssetRetrievalUnit> {

    List<FtsResultRow> searchByFts(
            @Param("ftsQuery") String ftsQuery,
            @Param("snapshotIds") List<String> snapshotIds,
            @Param("limit") int limit);
}
