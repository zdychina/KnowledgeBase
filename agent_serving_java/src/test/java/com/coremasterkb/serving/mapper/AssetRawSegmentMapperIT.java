package com.coremasterkb.serving.mapper;

import com.coremasterkb.serving.AbstractPgIntegrationTest;
import com.coremasterkb.serving.mapper.AssetRetrievalUnitMapper;
import com.coremasterkb.serving.mapper.result.FtsResultRow;
import com.coremasterkb.serving.mapper.result.SegmentWithMetaRow;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

@DisplayName("AssetRawSegmentMapper IT")
class AssetRawSegmentMapperIT extends AbstractPgIntegrationTest {

    @Autowired
    private AssetRetrievalUnitMapper unitMapper;

    @Autowired
    private AssetRawSegmentMapper rawSegmentMapper;

    @Test
    @DisplayName("selectWithMeta returns segments with metadata")
    void selectWithMetaReturnsSegments() {
        // First get some retrieval unit IDs via FTS
        List<FtsResultRow> ftsResults = unitMapper.searchByFts("SMF", activeScope.snapshotIds(), 5);
        assumeTrue(!ftsResults.isEmpty(), "No FTS results — skipping segment test");

        // Use source segment IDs from FTS results
        List<String> segIds = ftsResults.stream()
                .map(FtsResultRow::getSourceSegmentId)
                .filter(id -> id != null && !id.isBlank())
                .distinct()
                .limit(5)
                .toList();
        assumeTrue(!segIds.isEmpty(), "No source segment IDs in FTS results — skipping");

        List<SegmentWithMetaRow> segments = rawSegmentMapper.selectWithMeta(segIds, activeScope.snapshotIds());
        assertThat(segments).isNotEmpty();
        assertThat(segments.get(0).getId()).isNotNull();
    }
}
