package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.EntityRef;
import com.coremasterkb.serving.domain.TreeNavigation;
import com.coremasterkb.serving.mapper.AssetRawSegmentMapper;
import com.coremasterkb.serving.mapper.result.SectionPathCountRow;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * Rule-based (no LLM) section-tree navigator.
 *
 * <p>Given the query's entities, infers the document chapters (top-level
 * {@code section_path} titles) that most frequently contain those entities via a
 * single aggregation query over {@code asset_raw_segments.entity_refs_json}. The
 * resulting prefixes let the assembler prefer in-chapter results ("locate the
 * chapter, then retrieve"), without filtering anything out.</p>
 *
 * <p>Returns an empty set — meaning "no navigation, search the whole base" — when
 * there are no explicit entities, no matching segments, or no chapter is dominant
 * enough (the entity is spread thinly across the corpus).</p>
 */
@Component
public class TreeNavigator {

    private static final Logger log = LoggerFactory.getLogger(TreeNavigator.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** A chapter must hold at least this share of the entity's hits to count as relevant (soft weighting). */
    private static final double DOMINANCE_THRESHOLD = 0.15;
    /** Cap on the number of navigated chapters. */
    private static final int MAX_PREFIXES = 3;

    // --- Hard-filter confidence gate (PageIndex-style "locate then retrieve") ---
    // Hard filtering narrows the retrieval SQL itself, so a wrong inference would hard-miss.
    // We only enable it when the signal is strongly concentrated AND backed by enough samples.
    // (Constants for now, like DOMINANCE_THRESHOLD; can move to domain.yaml later, cf. intent_strategy.)
    /** The dominant chapter must hold at least this share of hits to justify a hard filter. */
    private static final double HARD_DOMINANCE_THRESHOLD = 0.6;
    /** Minimum total entity hits before hard filtering is statistically meaningful. */
    private static final int MIN_HITS_FOR_HARD = 5;

    private final AssetRawSegmentMapper segmentMapper;

    public TreeNavigator(AssetRawSegmentMapper segmentMapper) {
        this.segmentMapper = segmentMapper;
    }

    /**
     * Infer the relevant chapters for the query entities.
     *
     * <p>Always produces {@code softSections} (chapters ≥ {@link #DOMINANCE_THRESHOLD}, capped at
     * {@link #MAX_PREFIXES}) for ranking bias. Additionally sets {@code hardFilter}=true with
     * {@code hardPrefixes} (chapters ≥ {@link #HARD_DOMINANCE_THRESHOLD}) when the signal is
     * confident enough to narrow retrieval — a clearly dominant chapter backed by ≥
     * {@link #MIN_HITS_FOR_HARD} hits. Returns {@link TreeNavigation#empty()} for full-base search.</p>
     */
    public TreeNavigation inferSections(List<EntityRef> entities, List<String> snapshotIds) {
        if (snapshotIds == null || snapshotIds.isEmpty()) {
            return TreeNavigation.empty();
        }
        List<String> names = entityNames(entities);
        if (names.isEmpty()) {
            return TreeNavigation.empty();  // no explicit entity → do not narrow
        }

        List<SectionPathCountRow> rows;
        try {
            rows = segmentMapper.selectSectionPathsByEntities(names, snapshotIds);
        } catch (Exception e) {
            log.warn("Tree navigation query failed (non-fatal, full-base fallback): {}", e.getMessage());
            return TreeNavigation.empty();
        }
        if (rows == null || rows.isEmpty()) {
            return TreeNavigation.empty();
        }

        // Aggregate hit counts by top-level chapter prefix.
        Map<String, Integer> byPrefix = new LinkedHashMap<>();
        long total = 0;
        for (SectionPathCountRow row : rows) {
            String prefix = prefixOf(row.getSectionPath());
            if (prefix == null) continue;
            byPrefix.merge(prefix, row.getCnt(), Integer::sum);
            total += row.getCnt();
        }
        if (total == 0 || byPrefix.isEmpty()) {
            return TreeNavigation.empty();
        }

        final long t = total;
        // Soft weighting (unchanged): chapters above the soft threshold, top-N, lower-cased.
        Set<String> softSections = byPrefix.entrySet().stream()
                .sorted(Map.Entry.<String, Integer>comparingByValue().reversed())
                .filter(en -> (double) en.getValue() / t >= DOMINANCE_THRESHOLD)
                .limit(MAX_PREFIXES)
                .map(Map.Entry::getKey)
                .collect(Collectors.toCollection(LinkedHashSet::new));

        if (softSections.isEmpty()) {
            return TreeNavigation.empty();
        }

        // Hard-filter gate: strongly-dominant chapters (≥ HARD threshold) with enough samples.
        List<String> hardPrefixes = byPrefix.entrySet().stream()
                .sorted(Map.Entry.<String, Integer>comparingByValue().reversed())
                .filter(en -> (double) en.getValue() / t >= HARD_DOMINANCE_THRESHOLD)
                .map(Map.Entry::getKey)
                .toList();
        boolean hardFilter = total >= MIN_HITS_FOR_HARD && !hardPrefixes.isEmpty();

        log.info("[tree-nav] entities={} → soft={} hard={} (hardFilter={}, totalHits={})",
                names, softSections, hardPrefixes, hardFilter, total);
        return new TreeNavigation(softSections, hardFilter ? hardPrefixes : List.of(), hardFilter);
    }

    private static List<String> entityNames(List<EntityRef> entities) {
        List<String> names = new ArrayList<>();
        if (entities != null) {
            for (EntityRef e : entities) {
                if (e.name() != null && !e.name().isBlank()) {
                    names.add(e.name());
                }
                if (e.normalizedName() != null && !e.normalizedName().isBlank()
                        && !e.normalizedName().equals(e.name())) {
                    names.add(e.normalizedName());
                }
            }
        }
        return names;
    }

    /** Lower-cased title of the first section_path element; null if absent/unparseable. */
    static String prefixOf(String sectionPathJson) {
        if (sectionPathJson == null || sectionPathJson.isBlank() || "[]".equals(sectionPathJson)) {
            return null;
        }
        try {
            List<Map<String, Object>> path =
                    MAPPER.readValue(sectionPathJson, new TypeReference<List<Map<String, Object>>>() {});
            if (path.isEmpty()) return null;
            Object title = path.get(0).get("title");
            if (title == null) return null;
            String s = title.toString().trim();
            return s.isEmpty() ? null : s.toLowerCase();
        } catch (Exception e) {
            return null;
        }
    }
}
