package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.EntityRef;
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

    /** A chapter must hold at least this share of the entity's hits to count as relevant. */
    private static final double DOMINANCE_THRESHOLD = 0.15;
    /** Cap on the number of navigated chapters. */
    private static final int MAX_PREFIXES = 3;

    private final AssetRawSegmentMapper segmentMapper;

    public TreeNavigator(AssetRawSegmentMapper segmentMapper) {
        this.segmentMapper = segmentMapper;
    }

    /**
     * Infer the relevant chapter prefixes (lower-cased top-level section titles) for
     * the query entities. Empty set ⇒ full-base search (graceful fallback).
     */
    public Set<String> inferSections(List<EntityRef> entities, List<String> snapshotIds) {
        if (snapshotIds == null || snapshotIds.isEmpty()) {
            return Set.of();
        }
        List<String> names = entityNames(entities);
        if (names.isEmpty()) {
            return Set.of();  // no explicit entity → do not narrow
        }

        List<SectionPathCountRow> rows;
        try {
            rows = segmentMapper.selectSectionPathsByEntities(names, snapshotIds);
        } catch (Exception e) {
            log.warn("Tree navigation query failed (non-fatal, full-base fallback): {}", e.getMessage());
            return Set.of();
        }
        if (rows == null || rows.isEmpty()) {
            return Set.of();
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
            return Set.of();
        }

        final long t = total;
        Set<String> prefixes = byPrefix.entrySet().stream()
                .sorted(Map.Entry.<String, Integer>comparingByValue().reversed())
                .filter(en -> (double) en.getValue() / t >= DOMINANCE_THRESHOLD)
                .limit(MAX_PREFIXES)
                .map(Map.Entry::getKey)
                .collect(Collectors.toCollection(LinkedHashSet::new));

        if (!prefixes.isEmpty()) {
            log.info("[tree-nav] entities={} → chapters={}", names, prefixes);
        }
        return prefixes;
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
