package com.coremasterkb.serving.retrieval;

import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.RetrievalQuery;
import com.coremasterkb.serving.domain.ScoreChain;
import com.coremasterkb.serving.mapper.AssetRetrievalEmbeddingMapper;
import com.coremasterkb.serving.mapper.result.EmbeddingRow;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.stream.Collectors;

/**
 * Dense vector retriever using pgvector cosine distance (server-side ANN).
 *
 * <p>Delegates ranking entirely to PostgreSQL via the {@code <=>} operator,
 * avoiding the previous approach of loading all embeddings into the JVM.
 * Scope filter (facets_json JSONB containment) is pushed down to the SQL query.
 * When the scope filter eliminates all results, the query is retried without scope.</p>
 */
public class DenseVectorRetriever implements Retriever {

    private static final Logger log = LoggerFactory.getLogger(DenseVectorRetriever.class);
    private static final String SOURCE_NAME = "dense_vector";

    private final AssetRetrievalEmbeddingMapper embeddingMapper;

    public DenseVectorRetriever(AssetRetrievalEmbeddingMapper embeddingMapper) {
        this.embeddingMapper = embeddingMapper;
    }

    @Override
    public List<RetrievalCandidate> retrieve(RetrievalQuery query, List<String> snapshotIds, int topK) {
        if (snapshotIds == null || snapshotIds.isEmpty()) {
            return Collections.emptyList();
        }
        float[] queryVec = query.queryEmbedding();
        if (queryVec == null || queryVec.length == 0) {
            return Collections.emptyList();
        }

        String vectorStr = formatVector(queryVec);
        List<String> scopeParams = FtsRetriever.buildScopeJsonParams(query.scope());

        List<EmbeddingRow> rows = embeddingMapper.selectTopKByVector(
                snapshotIds, vectorStr, queryVec.length, scopeParams, topK);

        if (rows.isEmpty() && !scopeParams.isEmpty()) {
            log.info("Scope filter eliminated all dense results, retrying without scope");
            rows = embeddingMapper.selectTopKByVector(
                    snapshotIds, vectorStr, queryVec.length, List.of(), topK);
        }

        return rows.stream().map(this::toCandidate).collect(Collectors.toList());
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    /** Format a float array as a pgvector literal: [v0,v1,...,vn] */
    static String formatVector(float[] vec) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < vec.length; i++) {
            if (i > 0) sb.append(',');
            sb.append(vec[i]);
        }
        sb.append("]");
        return sb.toString();
    }

    private RetrievalCandidate toCandidate(EmbeddingRow row) {
        double score = row.getCosineScore();
        Map<String, Object> metadata = new HashMap<>();
        putIfNotNull(metadata, "document_snapshot_id", row.getDocumentSnapshotId());
        putIfNotNull(metadata, "text", row.getText());
        putIfNotNull(metadata, "title", row.getTitle());
        putIfNotNull(metadata, "block_type", row.getBlockType());
        putIfNotNull(metadata, "semantic_role", row.getSemanticRole());
        putIfNotNull(metadata, "source_refs_json", row.getSourceRefsJson());
        putIfNotNull(metadata, "facets_json", row.getFacetsJson());
        putIfNotNull(metadata, "target_type", row.getTargetType());
        putIfNotNull(metadata, "target_ref_json", row.getTargetRefJson());
        putIfNotNull(metadata, "unit_type", row.getUnitType());
        putIfNotNull(metadata, "source_segment_id", row.getSourceSegmentId());

        return new RetrievalCandidate(
                row.getRetrievalUnitId(),
                score,
                SOURCE_NAME,
                metadata,
                new ScoreChain(score, 0.0, 0.0, List.of(SOURCE_NAME))
        );
    }

    private void putIfNotNull(Map<String, Object> map, String key, Object val) {
        if (val != null) {
            map.put(key, val);
        }
    }
}
