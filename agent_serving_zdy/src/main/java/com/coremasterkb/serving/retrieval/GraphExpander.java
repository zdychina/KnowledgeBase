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
 */
public class GraphExpander {

    private static final Logger log = LoggerFactory.getLogger(GraphExpander.class);

    private final AssetRawSegmentRelationMapper relationMapper;
    private final AssetRawSegmentMapper segmentMapper;

    public GraphExpander(AssetRawSegmentRelationMapper relationMapper,
                         AssetRawSegmentMapper segmentMapper) {
        this.relationMapper = relationMapper;
        this.segmentMapper = segmentMapper;
    }

    /**
     * Expand seed segment IDs by BFS up to maxDepth levels.
     *
     * @param seedIds       starting segments from source_refs_json
     * @param maxDepth      max BFS depth
     * @param relationTypes filter to these relation types (null = all)
     * @param maxResults    cap on total expanded segments
     * @param snapshotIds   optional snapshot scope filter
     * @return expanded segments (seeds excluded), each annotated with expansion depth
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

        Set<String> visited = new LinkedHashSet<>(seedIds);
        Set<String> frontier = new LinkedHashSet<>(seedIds);
        Map<String, Integer> expandedIds = new LinkedHashMap<>(); // neighborId -> depth

        for (int depth = 1; depth <= maxDepth; depth++) {
            if (frontier.isEmpty()) {
                break;
            }

            List<NeighborRow> neighbors = relationMapper.selectNeighbors(
                    new ArrayList<>(frontier), relationTypes, snapshotIds);

            Set<String> nextFrontier = new LinkedHashSet<>();
            for (NeighborRow row : neighbors) {
                String neighborId = row.getNeighborId();
                if (neighborId != null && !visited.contains(neighborId)) {
                    visited.add(neighborId);
                    nextFrontier.add(neighborId);
                    expandedIds.putIfAbsent(neighborId, depth);

                    if (expandedIds.size() >= maxResults) {
                        return resolveSegments(expandedIds, snapshotIds);
                    }
                }
            }
            frontier = nextFrontier;
        }

        if (expandedIds.isEmpty()) {
            return Collections.emptyList();
        }

        return resolveSegments(expandedIds, snapshotIds);
    }

    /**
     * Fetch full segment data for expanded segment IDs and build result rows.
     */
    private List<ExpandedSegmentRow> resolveSegments(
            Map<String, Integer> expandedIds, List<String> snapshotIds) {

        List<SegmentWithMetaRow> segments = segmentMapper.selectWithMeta(
                new ArrayList<>(expandedIds.keySet()), snapshotIds);

        return segments.stream()
                .filter(seg -> seg.getId() != null && expandedIds.containsKey(seg.getId()))
                .map(seg -> new ExpandedSegmentRow(seg, expandedIds.get(seg.getId())))
                .toList();
    }
}
