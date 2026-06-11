package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.EntityRef;
import com.coremasterkb.serving.domain.TreeNavigation;
import com.coremasterkb.serving.mapper.AssetRawSegmentMapper;
import com.coremasterkb.serving.mapper.result.SectionPathCountRow;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@DisplayName("TreeNavigator")
class TreeNavigatorTest {

    private AssetRawSegmentMapper mapper;
    private TreeNavigator navigator;

    @BeforeEach
    void setUp() {
        mapper = mock(AssetRawSegmentMapper.class);
        navigator = new TreeNavigator(mapper);
    }

    private static SectionPathCountRow row(String title, int cnt) {
        var r = new SectionPathCountRow();
        r.setSectionPath("[{\"title\":\"" + title + "\",\"level\":1}]");
        r.setCnt(cnt);
        return r;
    }

    private static EntityRef entity(String name) {
        return new EntityRef("network_element", name, name);
    }

    @Test
    @DisplayName("dominant chapter is inferred (soft); thin chapters are dropped")
    void dominantChapterInferred() {
        when(mapper.selectSectionPathsByEntities(any(), any()))
                .thenReturn(List.of(row("SMF", 8), row("UPF", 1)));

        TreeNavigation nav = navigator.inferSections(List.of(entity("SMF")), List.of("snap1"));

        // SMF = 8/9 ≈ 89% kept; UPF = 1/9 ≈ 11% < 15% threshold → dropped. Prefixes lower-cased.
        assertThat(nav.softSections()).containsExactly("smf");
    }

    @Test
    @DisplayName("strongly dominant chapter with enough samples enables the hard filter")
    void strongDominanceEnablesHardFilter() {
        // SMF = 8/9 ≈ 89% ≥ 0.6 hard threshold, total 9 ≥ 5 min sample → hard filter on.
        when(mapper.selectSectionPathsByEntities(any(), any()))
                .thenReturn(List.of(row("SMF", 8), row("UPF", 1)));

        TreeNavigation nav = navigator.inferSections(List.of(entity("SMF")), List.of("snap1"));

        assertThat(nav.hardFilter()).isTrue();
        assertThat(nav.hardPrefixes()).containsExactly("smf");
    }

    @Test
    @DisplayName("moderate dominance (< hard threshold) stays soft-only")
    void moderateDominanceSoftOnly() {
        // SMF 5/12≈42%, UPF 4/12≈33%, AMF 3/12=25% — all ≥15% soft, none ≥60% hard.
        when(mapper.selectSectionPathsByEntities(any(), any()))
                .thenReturn(List.of(row("SMF", 5), row("UPF", 4), row("AMF", 3)));

        TreeNavigation nav = navigator.inferSections(List.of(entity("SMF")), List.of("snap1"));

        assertThat(nav.softSections()).containsExactlyInAnyOrder("smf", "upf", "amf");
        assertThat(nav.hardFilter()).isFalse();
        assertThat(nav.hardPrefixes()).isEmpty();
    }

    @Test
    @DisplayName("dominant but too few samples → soft-only (not statistically meaningful)")
    void dominantButSmallSampleSoftOnly() {
        // SMF 3/4 = 75% ≥ 0.6, but total 4 < MIN_HITS_FOR_HARD (5) → no hard filter.
        when(mapper.selectSectionPathsByEntities(any(), any()))
                .thenReturn(List.of(row("SMF", 3), row("UPF", 1)));

        TreeNavigation nav = navigator.inferSections(List.of(entity("SMF")), List.of("snap1"));

        assertThat(nav.softSections()).contains("smf");
        assertThat(nav.hardFilter()).isFalse();
    }

    @Test
    @DisplayName("no explicit entity → empty (full-base search), no DB query")
    void noEntityNoNavigation() {
        TreeNavigation nav = navigator.inferSections(List.of(), List.of("snap1"));
        assertThat(nav.softSections()).isEmpty();
        assertThat(nav.hardFilter()).isFalse();
        verifyNoInteractions(mapper);
    }

    @Test
    @DisplayName("entity spread thinly across many chapters → empty (no dominant chapter)")
    void spreadEntityNoDominant() {
        List<SectionPathCountRow> rows = new java.util.ArrayList<>();
        for (int i = 0; i < 10; i++) {
            rows.add(row("ch" + i, 1));  // each 10% < 15% threshold
        }
        when(mapper.selectSectionPathsByEntities(any(), any())).thenReturn(rows);

        TreeNavigation nav = navigator.inferSections(List.of(entity("SMF")), List.of("snap1"));
        assertThat(nav.softSections()).isEmpty();
        assertThat(nav.hardFilter()).isFalse();
    }

    @Test
    @DisplayName("no snapshots → empty, no DB query")
    void noSnapshots() {
        TreeNavigation nav = navigator.inferSections(List.of(entity("SMF")), List.of());
        assertThat(nav.softSections()).isEmpty();
        assertThat(nav.hardFilter()).isFalse();
        verifyNoInteractions(mapper);
    }
}
