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

    /**
     * Return the top-K nearest neighbours using pgvector cosine distance.
     * Scoring and ranking are done server-side; no in-JVM vector math needed.
     * Scope filter (facets_json JSONB containment) is pushed down to SQL.
     * Pass an empty {@code scopeJsonParams} list to skip scope filtering.
     */
    List<EmbeddingRow> selectTopKByVector(
            @Param("snapshotIds") List<String> snapshotIds,
            @Param("queryVector") String queryVector,
            @Param("dim") int dim,
            @Param("scopeJsonParams") List<String> scopeJsonParams,
            @Param("topK") int topK);
}
