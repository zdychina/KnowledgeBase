package com.coremasterkb.serving.mapper;

import com.coremasterkb.serving.mapper.result.DocumentSourceRow;
import org.apache.ibatis.annotations.Param;

import java.util.List;

public interface AssetDocumentMapper {

    List<DocumentSourceRow> selectDocumentSources(
            @Param("documentIds") List<String> documentIds,
            @Param("snapshotIds") List<String> snapshotIds);
}
