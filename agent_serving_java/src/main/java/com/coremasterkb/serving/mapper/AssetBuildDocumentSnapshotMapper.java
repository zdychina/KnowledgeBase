package com.coremasterkb.serving.mapper;

import com.coremasterkb.serving.entity.AssetBuildDocumentSnapshot;
import org.apache.ibatis.annotations.Param;

import java.util.List;

public interface AssetBuildDocumentSnapshotMapper {

    List<AssetBuildDocumentSnapshot> selectByBuildIdAndStatus(
            @Param("buildId") String buildId,
            @Param("selectionStatus") String selectionStatus);
}
