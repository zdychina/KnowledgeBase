package com.coremasterkb.serving.mapper;

import com.coremasterkb.serving.mapper.result.EmbeddingRow;
import org.apache.ibatis.annotations.Param;

import java.util.List;

public interface AssetRetrievalEmbeddingMapper {

    /**
     * Load embeddings (with unit metadata) scoped to the given snapshots.
     * Only rows where text_kind = 'search_text' are returned.
     * {@code limit} acts as a safety cap to prevent unbounded memory use.
     */
    List<EmbeddingRow> selectWithUnitMeta(
            @Param("snapshotIds") List<String> snapshotIds,
            @Param("limit") int limit);
}
