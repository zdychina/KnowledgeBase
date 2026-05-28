package com.coremasterkb.serving.retrieval;

import com.coremasterkb.serving.mapper.AssetRawSegmentMapper;
import com.coremasterkb.serving.mapper.AssetRawSegmentRelationMapper;
import com.coremasterkb.serving.mapper.result.ExpandedSegmentRow;
import com.coremasterkb.serving.mapper.result.NeighborRow;
import com.coremasterkb.serving.mapper.result.SegmentWithMetaRow;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;

/**
 * BFS graph expander for raw segment relations.
 *
 * <p>Expands seed segments from source_refs_json via relation traversal.
 * Each BFS depth level issues one SQL query via
 * {@link AssetRawSegmentRelationMapper#selectNeighbors}.
 * Returns expanded segments with distance and relation type metadata.</p>
 *
 * <p>Phase 1 – Traversal Budget: total nodes explored is capped at {@value #TOTAL_BUDGET},
 * regardless of the caller's {@code maxResults} argument.
 * Phase 2 – Relation Priority: neighbors at each BFS level are processed in priority order
 * so that high-value discourse relations (elaborates, conditions, …) fill the budget first.</p>
 */
public class GraphExpander {

    private static final Logger log = LoggerFactory.getLogger(GraphExpander.class);

    /** Hard ceiling on expanded nodes regardless of caller-supplied maxResults. */
    private static final int TOTAL_BUDGET = 20;

    /**
     * Relation-type priority: lower number = higher priority = consumed first within budget.
     * Mirrors the RST weight scale in ContextAssembler (elaborates 1.5 → highest, etc.).
     */
    private static final Map<String, Integer> RELATION_PRIORITY = Map.ofEntries(
            Map.entry("entity_relation",       0),
            Map.entry("elaborates",            1),
            Map.entry("conditions",            2),
            Map.entry("backgrounds",           3),
            Map.entry("enables",               4),
            Map.entry("results_in",            5),
            Map.entry("sequences",             6),
            Map.entry("contrasts_with",        7),
            Map.entry("causes",                8),
            Map.entry("parallels",             9),
            Map.entry("section_header_of",    10),
            Map.entry("same_section",         11),
            Map.entry("previous",             12),
            Map.entry("next",                 13),
            Map.entry("same_parent_section",  14)
    );

    private final AssetRawSegmentRelationMapper relationMapper;
    private final AssetRawSegmentMapper segmentMapper;

    public GraphExpander(AssetRawSegmentRelationMapper relationMapper,
                         AssetRawSegmentMapper segmentMapper) {
        this.relationMapper = relationMapper;
        this.segmentMapper = segmentMapper;
    }

    /** Per-node metadata tracked during BFS. */
    private record NodeInfo(int depth, String relationType) {}

    /**
     * Expand seed segment IDs by BFS up to maxDepth levels.
     *
     * @param seedIds       starting segments from source_refs_json
     * @param maxDepth      max BFS depth
     * @param relationTypes filter to these relation types (null = all)
     * @param maxResults    caller-supplied cap; effective cap = min(maxResults, TOTAL_BUDGET)
     * @param snapshotIds   optional snapshot scope filter
     * @return expanded segments (seeds excluded), each annotated with depth and relation type
     */
    public List<ExpandedSegmentRow> expand(
            List<String> seedIds,
            int maxDepth,
            List<String> relationTypes,
            int maxResults,
            List<String> snapshotIds) {

        if (seedIds == null || seedIds.isEmpty()) {
            return Collections.emptyList();
        }

        int budget = Math.min(maxResults, TOTAL_BUDGET);

        Set<String> visited = new LinkedHashSet<>(seedIds);
        Set<String> frontier = new LinkedHashSet<>(seedIds);
        Map<String, NodeInfo> expandedNodes = new LinkedHashMap<>();  // neighborId -> (depth, relationType)
        Map<String, String>   rootSeed      = new LinkedHashMap<>();  // nodeId -> original seed ID

        for (String sid : seedIds) {
            rootSeed.put(sid, sid);
        }

        for (int depth = 1; depth <= maxDepth; depth++) {
            if (frontier.isEmpty()) break;

            List<NeighborRow> neighbors = relationMapper.selectNeighbors(
                    new ArrayList<>(frontier), relationTypes, snapshotIds);

            // Process highest-priority relations first so they claim budget before structural ones
            neighbors.sort(Comparator.comparingInt(n ->
                    RELATION_PRIORITY.getOrDefault(n.getRelationType(), 99)));

            Set<String> nextFrontier = new LinkedHashSet<>();
            for (NeighborRow row : neighbors) {
                String neighborId = row.getNeighborId();
                if (neighborId == null || visited.contains(neighborId)) continue;

                visited.add(neighborId);
                nextFrontier.add(neighborId);
                String relType = row.getRelationType() != null ? row.getRelationType() : "";
                expandedNodes.put(neighborId, new NodeInfo(depth, relType));
                rootSeed.putIfAbsent(neighborId,
                        rootSeed.getOrDefault(row.getFromId(), row.getFromId()));

                if (expandedNodes.size() >= budget) {
                    return resolveSegments(expandedNodes, rootSeed, snapshotIds);
                }
            }
            frontier = nextFrontier;
        }

        if (expandedNodes.isEmpty()) {
            return Collections.emptyList();
        }

        return resolveSegments(expandedNodes, rootSeed, snapshotIds);
    }

    private List<ExpandedSegmentRow> resolveSegments(
            Map<String, NodeInfo> expandedNodes,
            Map<String, String> rootSeed,
            List<String> snapshotIds) {

        List<SegmentWithMetaRow> segments = segmentMapper.selectWithMeta(
                new ArrayList<>(expandedNodes.keySet()), snapshotIds);

        return segments.stream()
                .filter(seg -> seg.getId() != null && expandedNodes.containsKey(seg.getId()))
                .map(seg -> {
                    NodeInfo info = expandedNodes.get(seg.getId());
                    return new ExpandedSegmentRow(
                            seg,
                            info.depth(),
                            rootSeed.getOrDefault(seg.getId(), ""),
                            info.relationType()
                    );
                })
                .toList();
    }
}
