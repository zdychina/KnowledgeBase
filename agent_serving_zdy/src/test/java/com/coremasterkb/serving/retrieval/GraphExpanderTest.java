package com.coremasterkb.serving.retrieval;

import com.coremasterkb.serving.mapper.AssetRawSegmentMapper;
import com.coremasterkb.serving.mapper.AssetRawSegmentRelationMapper;
import com.coremasterkb.serving.mapper.result.ExpandedSegmentRow;
import com.coremasterkb.serving.mapper.result.NeighborRow;
import com.coremasterkb.serving.mapper.result.SegmentWithMetaRow;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link GraphExpander} budget-allocation priority (PRD-03 fix).
 *
 * <p>Verifies that when an intent supplies an explicit {@code relationTypes} list, the list's
 * order — not the global RST table — drives which relations claim the limited budget. This is
 * what makes an intent's signature relations (causal for troubleshooting, contrasts_with for
 * comparison) survive when generic {@code elaborates} neighbors are far more numerous.</p>
 */
@DisplayName("GraphExpander priority")
class GraphExpanderTest {

    private AssetRawSegmentRelationMapper relationMapper;
    private AssetRawSegmentMapper segmentMapper;
    private GraphExpander expander;

    private static final List<String> SNAPSHOTS = List.of("snap1");
    private static final List<String> SEEDS = List.of("seed1");

    @BeforeEach
    void setUp() {
        relationMapper = mock(AssetRawSegmentRelationMapper.class);
        segmentMapper = mock(AssetRawSegmentMapper.class);
        expander = new GraphExpander(relationMapper, segmentMapper);

        // selectWithMeta returns rows for every candidate id; resolveSegments filters to the
        // ids that actually claimed the budget, so a superset here is harmless.
        when(segmentMapper.selectWithMeta(any(), any())).thenReturn(List.of(
                seg("e1"), seg("e2"), seg("e3"), seg("c1"), seg("r1")));
    }

    /**
     * seed1 has 3 elaborates neighbors but only 1 causes + 1 results_in. With budget = 2 and the
     * troubleshooting relationTypes order [causes, results_in, ...], the causal neighbors must win
     * the budget. Under the old global table (elaborates=1 highest), they would be crowded out.
     */
    @Test
    @DisplayName("intent relationTypes order lets causal relations claim the budget")
    void intentOrderPrioritisesSignatureRelations() {
        when(relationMapper.selectNeighbors(any(), any(), any())).thenReturn(neighbors(
                neighbor("e1", "elaborates"),
                neighbor("e2", "elaborates"),
                neighbor("e3", "elaborates"),
                neighbor("c1", "causes"),
                neighbor("r1", "results_in")));

        List<String> troubleshooting = List.of(
                "causes", "results_in", "enables", "conditions", "elaborates", "backgrounds");

        List<ExpandedSegmentRow> result = expander.expand(SEEDS, 1, troubleshooting, 2, SNAPSHOTS);

        List<String> ids = result.stream().map(r -> r.segment().getId()).toList();
        assertThat(ids).containsExactlyInAnyOrder("c1", "r1");
        assertThat(ids).doesNotContain("e1", "e2", "e3");
        assertThat(result).extracting(ExpandedSegmentRow::relationType)
                .containsExactlyInAnyOrder("causes", "results_in");
    }

    /**
     * comparison: contrasts_with must beat the more-numerous elaborates neighbors under its
     * relationTypes order [contrasts_with, parallels, elaborates].
     */
    @Test
    @DisplayName("comparison surfaces contrasts_with over numerous elaborates")
    void comparisonOrderSurfacesContrast() {
        when(relationMapper.selectNeighbors(any(), any(), any())).thenReturn(neighbors(
                neighbor("e1", "elaborates"),
                neighbor("e2", "elaborates"),
                neighbor("e3", "elaborates"),
                neighbor("c1", "contrasts_with")));

        List<String> comparison = List.of("contrasts_with", "parallels", "elaborates");

        List<ExpandedSegmentRow> result = expander.expand(SEEDS, 1, comparison, 1, SNAPSHOTS);

        assertThat(result).hasSize(1);
        assertThat(result.get(0).segment().getId()).isEqualTo("c1");
        assertThat(result.get(0).relationType()).isEqualTo("contrasts_with");
    }

    /**
     * With no relationTypes list, the global RST table applies (elaborates = highest priority),
     * preserving the original behavior for non-intent-specific expansion.
     */
    @Test
    @DisplayName("no relationTypes falls back to the global RST priority table")
    void noRelationTypesUsesGlobalTable() {
        when(relationMapper.selectNeighbors(any(), any(), any())).thenReturn(neighbors(
                neighbor("e1", "elaborates"),
                neighbor("e2", "elaborates"),
                neighbor("c1", "causes"),
                neighbor("r1", "results_in")));

        List<ExpandedSegmentRow> result = expander.expand(SEEDS, 1, null, 2, SNAPSHOTS);

        // elaborates (global priority 1) wins over results_in (5) and causes (8)
        List<String> ids = result.stream().map(r -> r.segment().getId()).toList();
        assertThat(ids).containsExactlyInAnyOrder("e1", "e2");
    }

    // ---- helpers ----

    /** Mutable list — GraphExpander sorts neighbors in place. */
    private static List<NeighborRow> neighbors(NeighborRow... rows) {
        return new ArrayList<>(List.of(rows));
    }

    private static NeighborRow neighbor(String neighborId, String relationType) {
        NeighborRow row = new NeighborRow();
        row.setFromId("seed1");
        row.setNeighborId(neighborId);
        row.setRelationType(relationType);
        return row;
    }

    private static SegmentWithMetaRow seg(String id) {
        SegmentWithMetaRow row = new SegmentWithMetaRow();
        row.setId(id);
        row.setRawText("text-" + id);
        return row;
    }
}
