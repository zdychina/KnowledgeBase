package com.coremasterkb.serving.mapper;

import com.coremasterkb.serving.entity.AssetPublishRelease;
import org.apache.ibatis.annotations.Param;

import java.util.List;

public interface AssetPublishReleaseMapper {

    List<AssetPublishRelease> selectActiveByDomain(@Param("domain") String domain);
}
