package com.coremasterkb.serving.retrieval;

import com.coremasterkb.serving.AbstractPgIntegrationTest;
import com.coremasterkb.serving.mapper.AssetRawSegmentMapper;
import com.coremasterkb.serving.mapper.AssetRawSegmentRelationMapper;
import com.coremasterkb.serving.mapper.AssetRetrievalUnitMapper;
import com.coremasterkb.serving.mapper.result.ExpandedSegmentRow;
import com.coremasterkb.serving.mapper.result.FtsResultRow;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

@DisplayName("GraphExpander IT")
class GraphExpanderIT extends AbstractPgIntegrationTest {

    @Autowired
    private AssetRawSegmentRelationMapper relationMapper;

    @Autowired
    private AssetRawSegmentMapper segmentMapper;

    @Autowired
    private AssetRetrievalUnitMapper unitMapper;

    private GraphExpander expander;

    @BeforeEach
    void setUp() {
        expander = new GraphExpander(relationMapper, segmentMapper);
    }

    @Test
    @DisplayName("expand with depth=1 returns expansion results (may be empty)")
    void expandDepth1() {
        List<FtsResultRow> ftsResults = unitMapper.searchByFts("SMF", activeScope.snapshotIds(), 5);
        assumeTrue(!ftsResults.isEmpty(), "No FTS results — skipping graph expander test");

        List<String> segIds = ftsResults.stream()
                .map(FtsResultRow::getSourceSegmentId)
                .filter(id -> id != null && !id.isBlank())
                .distinct()
                .limit(3)
                .toList();
        assumeTrue(!segIds.isEmpty(), "No segment IDs — skipping");

        List<ExpandedSegmentRow> results = expander.expand(
                segIds, 1, List.of("next", "previous", "same_section"), 10, activeScope.snapshotIds());
        assertThat(results).isNotNull();
    }
}
