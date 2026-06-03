package com.coremasterkb.serving.mapper;

import com.coremasterkb.serving.mapper.result.SectionPathCountRow;
import com.coremasterkb.serving.mapper.result.SegmentWithMetaRow;
import org.apache.ibatis.annotations.Param;

import java.util.List;

public interface AssetRawSegmentMapper {

    List<SegmentWithMetaRow> selectWithMeta(
            @Param("segmentIds") List<String> segmentIds,
            @Param("snapshotIds") List<String> snapshotIds);

    /**
     * TreeNavigator support: count segments per section_path that contain any of the
     * given entity names (via entity_refs_json), within the active snapshots.
     * Returns the most populated section paths first.
     */
    List<SectionPathCountRow> selectSectionPathsByEntities(
            @Param("entityNames") List<String> entityNames,
            @Param("snapshotIds") List<String> snapshotIds);
}
