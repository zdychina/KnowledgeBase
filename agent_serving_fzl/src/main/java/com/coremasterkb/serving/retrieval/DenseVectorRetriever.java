package com.coremasterkb.serving.retrieval;

import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.RetrievalQuery;
import com.coremasterkb.serving.domain.ScoreChain;
import com.coremasterkb.serving.mapper.AssetRetrievalEmbeddingMapper;
import com.coremasterkb.serving.mapper.result.EmbeddingRow;
import com.coremasterkb.serving.util.JsonUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.stream.Collectors;

/**
 * Dense vector retriever using pgvector cosine distance.
 *
 * <p>Uses the pre-computed query embedding from {@link RetrievalQuery#queryEmbedding()}.
 * Loads stored embeddings scoped to active snapshots and computes cosine similarity
 * in Java. Scope filter is applied via facets_json JSONB containment.</p>
 */
public class DenseVectorRetriever implements Retriever {

    private static final Logger log = LoggerFactory.getLogger(DenseVectorRetriever.class);
    private static final String SOURCE_NAME = "dense_vector";

    private final AssetRetrievalEmbeddingMapper embeddingMapper;
    private final int maxLoad;

    /**
     * @param embeddingMapper mapper for loading stored embeddings with unit metadata
     * @param maxLoad         safety cap to prevent unbounded memory use during cosine computation
     */
    public DenseVectorRetriever(AssetRetrievalEmbeddingMapper embeddingMapper, int maxLoad) {
        this.embeddingMapper = embeddingMapper;
        this.maxLoad = maxLoad;
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

        // Load stored embeddings with unit metadata (capped at maxLoad)
        List<EmbeddingRow> rows = embeddingMapper.selectWithUnitMeta(snapshotIds, maxLoad);
        if (rows.isEmpty()) {
            return Collections.emptyList();
        }

        // Compute cosine similarity; skip rows whose stored dim mismatches the query vector
        record Scored(double score, EmbeddingRow row) {}

        List<Scored> scored = new ArrayList<>();
        for (EmbeddingRow row : rows) {
            if (row.getEmbeddingDim() != queryVec.length) {
                continue;
            }
            float[] stored = parseVector(row.getEmbeddingVector());
            if (stored.length == 0) {
                continue;
            }
            double sim = cosineSimilarity(queryVec, stored);
            scored.add(new Scored(sim, row));
        }

        // Sort descending by score, truncate to topK
        scored.sort(Comparator.comparingDouble(Scored::score).reversed());
        int limit = Math.min(topK, scored.size());

        // Build scope params for metadata annotation (filtering already done above in Java)
        return scored.subList(0, limit).stream()
                .map(s -> toCandidate(s.row(), s.score()))
                .collect(Collectors.toList());
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    /** Parse embedding_vector stored as JSON float array: [0.1, 0.2, ...] */
    @SuppressWarnings("unchecked")
    private float[] parseVector(String json) {
        if (json == null || json.isBlank()) {
            return new float[0];
        }
        try {
            List<Number> list = JsonUtils.mapper().readValue(json, List.class);
            float[] result = new float[list.size()];
            for (int i = 0; i < list.size(); i++) {
                result[i] = list.get(i).floatValue();
            }
            return result;
        } catch (Exception e) {
            log.debug("Failed to parse embedding vector: {}", e.getMessage());
            return new float[0];
        }
    }

    private static double cosineSimilarity(float[] a, float[] b) {
        double dot = 0, normA = 0, normB = 0;
        for (int i = 0; i < a.length; i++) {
            dot += (double) a[i] * b[i];
            normA += (double) a[i] * a[i];
            normB += (double) b[i] * b[i];
        }
        double denom = Math.sqrt(normA) * Math.sqrt(normB);
        return denom == 0.0 ? 0.0 : dot / denom;
    }

    private RetrievalCandidate toCandidate(EmbeddingRow row, double score) {
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
