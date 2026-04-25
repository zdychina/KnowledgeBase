package com.coremasterkb.serving.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.coremasterkb.serving.entity.AssetDocument;
import com.coremasterkb.serving.mapper.result.DocumentSourceRow;
import org.apache.ibatis.annotations.Param;

import java.util.List;

public interface AssetDocumentMapper extends BaseMapper<AssetDocument> {

    List<DocumentSourceRow> selectDocumentSources(
            @Param("documentIds") List<String> documentIds,
            @Param("snapshotIds") List<String> snapshotIds);
}
