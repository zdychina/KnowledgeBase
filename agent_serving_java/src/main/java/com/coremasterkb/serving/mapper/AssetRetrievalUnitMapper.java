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

    /**
     * Entity-exact search: returns units whose entity_refs_json contains
     * any element with a "name" field matching one of the given entityNames.
     */
    List<FtsResultRow> searchByEntityExact(
            @Param("entityNames") List<String> entityNames,
            @Param("snapshotIds") List<String> snapshotIds,
            @Param("limit") int limit);
}
