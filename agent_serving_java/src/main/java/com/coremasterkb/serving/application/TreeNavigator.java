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

import java.util.*;
import java.util.stream.Collectors;

/**
 * Rule-based (no LLM) section-tree navigator.
 *
 * <p>Given the query's entities, infers the document chapters (top-level
 * {@code section_path} titles) that most frequently contain those entities via a
 * single aggregation query over {@code asset_raw_segments.entity_refs_json}.
 */
@Component
public class TreeNavigator {

    private static final Logger log = LoggerFactory.getLogger(TreeNavigator.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static final double DOMINANCE_THRESHOLD = 0.15;
    private static final int MAX_PREFIXES = 3;
    private static final double HARD_DOMINANCE_THRESHOLD = 0.6;
    private static final int MIN_HITS_FOR_HARD = 5;

    private final AssetRawSegmentMapper segmentMapper;

    public TreeNavigator(AssetRawSegmentMapper segmentMapper) {
        this.segmentMapper = segmentMapper;
    }

    public TreeNavigation inferSections(List<EntityRef> entities, List<String> snapshotIds) {
        if (snapshotIds == null || snapshotIds.isEmpty()) {
            return TreeNavigation.empty();
        }
        List<String> names = entityNames(entities);
        if (names.isEmpty()) {
            return TreeNavigation.empty();
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
        Set<String> softSections = byPrefix.entrySet().stream()
                .sorted(Map.Entry.<String, Integer>comparingByValue().reversed())
                .filter(en -> (double) en.getValue() / t >= DOMINANCE_THRESHOLD)
                .limit(MAX_PREFIXES)
                .map(Map.Entry::getKey)
                .collect(Collectors.toCollection(LinkedHashSet::new));

        if (softSections.isEmpty()) {
            return TreeNavigation.empty();
        }

        List<String> hardPrefixes = byPrefix.entrySet().stream()
                .sorted(Map.Entry.<String, Integer>comparingByValue().reversed())
                .filter(en -> (double) en.getValue() / t >= HARD_DOMINANCE_THRESHOLD)
                .map(Map.Entry::getKey)
                .toList();
        boolean hardFilter = total >= MIN_HITS_FOR_HARD && !hardPrefixes.isEmpty();

        log.info("[tree-nav] entities={} -> soft={} hard={} (hardFilter={}, totalHits={})",
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
