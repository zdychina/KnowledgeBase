package com.coremasterkb.serving.operator.mapper;

import com.coremasterkb.serving.mapper.result.EmbeddingRow;
import org.apache.ibatis.annotations.Param;

import java.util.List;

/**
 * Operator-specific embedding retrieval mapper.
 *
 * <p>Unlike the existing {@code AssetRetrievalEmbeddingMapper.selectTopKByVector} (which assumes
 * one embedding per unit and ignores {@code text_kind}), this query filters by {@code text_kind}
 * so the {@code dense_vector} operator's "检索范围" (raw_text / question / both) parameter actually
 * changes what is searched. {@code DISTINCT ON (retrieval_unit_id)} keeps the best-scoring
 * embedding per unit, so a unit with several embeddings does not produce duplicate candidates.</p>
 *
 * <p>New file, new SQL — the existing mapper is left unchanged (PRD 决策 8).</p>
 */
public interface OperatorEmbeddingMapper {

    /**
     * Top-K nearest neighbours (pgvector cosine), restricted to the given {@code textKinds}.
     *
     * @param snapshotIds     in-scope document snapshot ids
     * @param queryVector     pgvector literal, e.g. {@code [0.1,0.2,...]}
     * @param dim             embedding dimension to match ({@code embedding_dim})
     * @param textKinds       text_kind values to include (e.g. {@code [raw_text]}, {@code [raw_text, question]})
     * @param scopeJsonParams optional facet JSONB containment params; empty list = no facet filter
     * @param topK            maximum candidates
     */
    List<EmbeddingRow> selectTopKByVectorAndTextKind(
            @Param("snapshotIds") List<String> snapshotIds,
            @Param("queryVector") String queryVector,
            @Param("dim") int dim,
            @Param("textKinds") List<String> textKinds,
            @Param("scopeJsonParams") List<String> scopeJsonParams,
            @Param("topK") int topK);
}
