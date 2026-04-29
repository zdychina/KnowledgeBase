package com.coremasterkb.serving.retrieval;

import com.coremasterkb.serving.client.ZhipuClient;
import com.coremasterkb.serving.domain.QueryPlan;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.mapper.AssetRetrievalEmbeddingMapper;
import com.coremasterkb.serving.mapper.result.EmbeddingRow;
import com.coremasterkb.serving.util.JsonUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.stream.Collectors;

/**
 * Dense vector retriever.
 *
 * Embeds the query text via Zhipu embedding-3 API (direct call),
 * then computes cosine similarity against stored embeddings in Java.
 * Returns empty list when Zhipu API key is not configured.
 */
public class DenseVectorRetriever implements Retriever {

    private static final Logger log = LoggerFactory.getLogger(DenseVectorRetriever.class);
    private static final String SOURCE_NAME = "dense_vector";
    private static final int DEFAULT_TOP_K = 50;

    private final ZhipuClient zhipuClient;
    private final AssetRetrievalEmbeddingMapper embeddingMapper;

    public DenseVectorRetriever(ZhipuClient zhipuClient,
                                AssetRetrievalEmbeddingMapper embeddingMapper) {
        this.zhipuClient     = zhipuClient;
        this.embeddingMapper = embeddingMapper;
    }

    @Override
    public String name() {
        return SOURCE_NAME;
    }

    @Override
    public List<RetrievalCandidate> retrieve(QueryPlan plan, List<String> snapshotIds) {
        if (!zhipuClient.isConfigured()) return Collections.emptyList();
        if (snapshotIds == null || snapshotIds.isEmpty()) return Collections.emptyList();

        String queryText = String.join(" ", plan.keywords());
        if (queryText.isBlank()) return Collections.emptyList();

        // Step 1: embed query via Zhipu API
        float[] queryVec = zhipuClient.embed(queryText);
        if (queryVec.length == 0) return Collections.emptyList();

        // Step 2: load stored embeddings with unit metadata
        List<EmbeddingRow> rows = embeddingMapper.selectWithUnitMeta(snapshotIds);
        if (rows.isEmpty()) return Collections.emptyList();

        // Step 3: cosine similarity
        record Scored(double score, EmbeddingRow row) {}
        List<Scored> scored = new ArrayList<>();
        for (EmbeddingRow row : rows) {
            float[] stored = parseVector(row.getEmbeddingVector());
            if (stored.length == 0 || stored.length != queryVec.length) continue;
            double sim = cosineSimilarity(queryVec, stored);
            scored.add(new Scored(sim, row));
        }

        // Step 4: sort desc, truncate to top-k
        scored.sort(Comparator.comparingDouble(Scored::score).reversed());
        int limit = Math.min(DEFAULT_TOP_K, scored.size());

        return scored.subList(0, limit).stream()
                .map(s -> rowToCandidate(s.row(), s.score()))
                .collect(Collectors.toList());
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    /** Parse embedding_vector stored as JSON float array: [0.1, 0.2, ...] */
    @SuppressWarnings("unchecked")
    private float[] parseVector(String json) {
        if (json == null || json.isBlank()) return new float[0];
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
            dot   += (double) a[i] * b[i];
            normA += (double) a[i] * a[i];
            normB += (double) b[i] * b[i];
        }
        double denom = Math.sqrt(normA) * Math.sqrt(normB);
        return denom == 0.0 ? 0.0 : dot / denom;
    }

    private RetrievalCandidate rowToCandidate(EmbeddingRow row, double score) {
        Map<String, Object> metadata = new HashMap<>();
        putIfNotNull(metadata, "document_snapshot_id", row.getDocumentSnapshotId());
        putIfNotNull(metadata, "text",                 row.getText());
        putIfNotNull(metadata, "title",                row.getTitle());
        putIfNotNull(metadata, "block_type",           row.getBlockType());
        putIfNotNull(metadata, "semantic_role",        row.getSemanticRole());
        putIfNotNull(metadata, "source_refs_json",     row.getSourceRefsJson());
        putIfNotNull(metadata, "facets_json",          row.getFacetsJson());
        putIfNotNull(metadata, "target_type",          row.getTargetType());
        putIfNotNull(metadata, "target_ref_json",      row.getTargetRefJson());
        putIfNotNull(metadata, "unit_type",            row.getUnitType());
        putIfNotNull(metadata, "source_segment_id",    row.getSourceSegmentId());
        return new RetrievalCandidate(row.getRetrievalUnitId(), score, SOURCE_NAME, metadata);
    }

    private void putIfNotNull(Map<String, Object> map, String key, Object val) {
        if (val != null) map.put(key, val);
    }
}
