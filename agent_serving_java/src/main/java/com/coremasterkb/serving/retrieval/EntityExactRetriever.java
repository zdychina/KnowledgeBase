package com.coremasterkb.serving.retrieval;

import com.coremasterkb.serving.domain.EntityRef;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.RetrievalQuery;
import com.coremasterkb.serving.domain.ScoreChain;
import com.coremasterkb.serving.mapper.AssetRetrievalUnitMapper;
import com.coremasterkb.serving.mapper.result.FtsResultRow;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;

/**
 * Entity-exact retriever: finds retrieval units whose entity_refs_json
 * contains any element with a "name" field matching one of the query entities.
 *
 * <p>Uses JSONB {@code @>} containment operator (GIN-indexable) for fast
 * lookups. Falls back to {@code jsonb_array_elements} when containment
 * params cannot be built.</p>
 *
 * <p>Fixed score = 0.95 for exact matches (high-confidence).</p>
 */
public class EntityExactRetriever implements Retriever {

    private static final Logger log = LoggerFactory.getLogger(EntityExactRetriever.class);
    private static final String SOURCE_NAME = "entity_exact";
    private static final double EXACT_MATCH_SCORE = 0.95;

    private final AssetRetrievalUnitMapper retrievalUnitMapper;

    public EntityExactRetriever(AssetRetrievalUnitMapper retrievalUnitMapper) {
        this.retrievalUnitMapper = retrievalUnitMapper;
    }

    @Override
    public List<RetrievalCandidate> retrieve(RetrievalQuery query, List<String> snapshotIds, int topK) {
        if (snapshotIds == null || snapshotIds.isEmpty()) {
            return Collections.emptyList();
        }

        // Primary: entity names from query.entities
        List<String> entityNames = new ArrayList<>();
        for (EntityRef ref : query.entities()) {
            if (ref.name() != null && !ref.name().isBlank()) {
                entityNames.add(ref.name());
            }
            if (ref.normalizedName() != null && !ref.normalizedName().isBlank()) {
                entityNames.add(ref.normalizedName());
            }
        }

        // Fallback: keywords as entity-like terms
        if (entityNames.isEmpty()) {
            entityNames.addAll(query.keywords().stream()
                    .filter(kw -> kw.length() >= 2)
                    .toList());
        }

        if (entityNames.isEmpty()) {
            return Collections.emptyList();
        }

        // Build JSONB containment params for @> operator (GIN-indexable)
        // Format: [{"name":"SMF"}] — each entity name becomes a containment check
        List<String> containmentParams = entityNames.stream()
                .map(name -> "[{\"name\":\"" + escapeJson(name) + "\"}]")
                .toList();

        List<FtsResultRow> rows = retrievalUnitMapper.searchByEntityExact(
                entityNames, snapshotIds, containmentParams, topK);

        return rows.stream()
                .map(row -> toCandidate(row, EXACT_MATCH_SCORE))
                .toList();
    }

    private RetrievalCandidate toCandidate(FtsResultRow row, double score) {
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
                row.getId(),
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

    /** Minimal JSON string escaping for entity names embedded in containment params. */
    private static String escapeJson(String s) {
        return s.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t");
    }
}
