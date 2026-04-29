package com.coremasterkb.serving.retrieval;

import com.coremasterkb.serving.domain.EntityRef;
import com.coremasterkb.serving.domain.QueryPlan;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.mapper.AssetRetrievalUnitMapper;
import com.coremasterkb.serving.mapper.result.FtsResultRow;

import java.util.*;
import java.util.stream.Collectors;

/**
 * Entity-exact retriever: finds retrieval units whose entity_refs_json
 * contains any of the query entities by name.
 * Fixed score = 0.95 (high-confidence exact match).
 */
public class EntityExactRetriever implements Retriever {

    private static final String SOURCE_NAME = "entity_exact";
    private static final double EXACT_MATCH_SCORE = 0.95;
    private static final int DEFAULT_LIMIT = 30;

    private final AssetRetrievalUnitMapper retrievalUnitMapper;

    public EntityExactRetriever(AssetRetrievalUnitMapper retrievalUnitMapper) {
        this.retrievalUnitMapper = retrievalUnitMapper;
    }

    @Override
    public String name() {
        return SOURCE_NAME;
    }

    @Override
    public List<RetrievalCandidate> retrieve(QueryPlan plan, List<String> snapshotIds) {
        if (snapshotIds == null || snapshotIds.isEmpty()) return Collections.emptyList();

        List<String> entityNames = plan.entityConstraints().stream()
                .map(EntityRef::name)
                .filter(n -> n != null && !n.isBlank())
                .collect(Collectors.toList());

        // Also include normalized names as alternative matches
        plan.entityConstraints().stream()
                .map(EntityRef::normalizedName)
                .filter(n -> n != null && !n.isBlank())
                .forEach(entityNames::add);

        if (entityNames.isEmpty()) return Collections.emptyList();

        List<FtsResultRow> rows = retrievalUnitMapper.searchByEntityExact(
                entityNames, snapshotIds, DEFAULT_LIMIT);

        return rows.stream()
                .map(row -> rowToCandidate(row, EXACT_MATCH_SCORE))
                .toList();
    }

    private RetrievalCandidate rowToCandidate(FtsResultRow row, double score) {
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
        return new RetrievalCandidate(row.getId(), score, SOURCE_NAME, metadata);
    }

    private void putIfNotNull(Map<String, Object> map, String key, Object val) {
        if (val != null) map.put(key, val);
    }
}
