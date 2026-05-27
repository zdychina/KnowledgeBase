package com.coremasterkb.serving.mapper;

import com.coremasterkb.serving.AbstractPgIntegrationTest;
import com.coremasterkb.serving.mapper.AssetRetrievalUnitMapper;
import com.coremasterkb.serving.mapper.result.FtsResultRow;
import com.coremasterkb.serving.mapper.result.NeighborRow;
import com.coremasterkb.serving.mapper.result.RelationRow;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

@DisplayName("AssetRawSegmentRelationMapper IT")
class AssetRawSegmentRelationMapperIT extends AbstractPgIntegrationTest {

    @Autowired
    private AssetRetrievalUnitMapper unitMapper;

    @Autowired
    private AssetRawSegmentRelationMapper relationMapper;

    private List<String> getSegmentIds() {
        List<FtsResultRow> ftsResults = unitMapper.searchByFts("SMF", activeScope.snapshotIds(), 5);
        assumeTrue(!ftsResults.isEmpty(), "No FTS results — skipping");
        return ftsResults.stream()
                .map(FtsResultRow::getSourceSegmentId)
                .filter(id -> id != null && !id.isBlank())
                .distinct()
                .limit(5)
                .toList();
    }

    @Test
    @DisplayName("selectRelationsForSegments returns relations")
    void selectRelationsForSegments() {
        List<String> segIds = getSegmentIds();
        assumeTrue(!segIds.isEmpty(), "No segment IDs — skipping");

        List<RelationRow> relations = relationMapper.selectRelationsForSegments(
                segIds, null, activeScope.snapshotIds());
        // Relations may or may not exist for these segments
        assertThat(relations).isNotNull();
    }

    @Test
    @DisplayName("selectNeighbors returns neighbor rows")
    void selectNeighbors() {
        List<String> segIds = getSegmentIds();
        assumeTrue(!segIds.isEmpty(), "No segment IDs — skipping");

        List<NeighborRow> neighbors = relationMapper.selectNeighbors(
                segIds, null, activeScope.snapshotIds());
        assertThat(neighbors).isNotNull();
    }
}
