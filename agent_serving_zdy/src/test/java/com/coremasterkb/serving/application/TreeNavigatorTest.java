package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.EntityRef;
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
    @DisplayName("dominant chapter is inferred; thin chapters are dropped")
    void dominantChapterInferred() {
        when(mapper.selectSectionPathsByEntities(any(), any()))
                .thenReturn(List.of(row("SMF", 8), row("UPF", 1)));

        var sections = navigator.inferSections(List.of(entity("SMF")), List.of("snap1"));

        // SMF = 8/9 ≈ 89% kept; UPF = 1/9 ≈ 11% < 15% threshold → dropped. Prefixes lower-cased.
        assertThat(sections).containsExactly("smf");
    }

    @Test
    @DisplayName("no explicit entity → empty (full-base search), no DB query")
    void noEntityNoNavigation() {
        var sections = navigator.inferSections(List.of(), List.of("snap1"));
        assertThat(sections).isEmpty();
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

        var sections = navigator.inferSections(List.of(entity("SMF")), List.of("snap1"));
        assertThat(sections).isEmpty();
    }

    @Test
    @DisplayName("no snapshots → empty, no DB query")
    void noSnapshots() {
        assertThat(navigator.inferSections(List.of(entity("SMF")), List.of())).isEmpty();
        verifyNoInteractions(mapper);
    }
}
