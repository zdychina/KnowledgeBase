package com.coremasterkb.serving.retrieval;

import com.coremasterkb.serving.domain.ExpansionConfig;
import com.coremasterkb.serving.domain.QueryPlan;
import com.coremasterkb.serving.mapper.result.ExpandedSegmentRow;
import com.coremasterkb.serving.mapper.result.NeighborRow;
import com.coremasterkb.serving.mapper.result.SegmentWithMetaRow;
import com.coremasterkb.serving.repository.AssetRepository;

import java.util.*;

/**
 * BFS graph expansion over raw segment relations.
 * Each BFS depth level issues one SQL query via AssetRepository.getNeighbors().
 */
public class GraphExpander {

    private final AssetRepository repo;

    public GraphExpander(AssetRepository repo) {
        this.repo = repo;
    }

    /**
     * Expand seed segment IDs by BFS up to config.maxRelationDepth levels.
     *
     * @return expanded segments (seeds excluded), each annotated with expansion depth
     */
    public List<ExpandedSegmentRow> expand(
            List<String> seedIds, QueryPlan plan, List<String> snapshotIds) {
        ExpansionConfig cfg = plan.expansion();
        if (!cfg.enableRelationExpansion() || seedIds == null || seedIds.isEmpty()) {
            return Collections.emptyList();
        }

        List<String> relationTypes = cfg.relationTypes();
        int maxDepth = cfg.maxRelationDepth();

        Set<String> visited = new HashSet<>(seedIds);
        Set<String> frontier = new HashSet<>(seedIds);
        Map<String, Integer> expandedIds = new LinkedHashMap<>(); // neighborId → depth

        for (int depth = 1; depth <= maxDepth; depth++) {
            if (frontier.isEmpty()) break;

            List<NeighborRow> neighbors =
                    repo.getNeighbors(new ArrayList<>(frontier), relationTypes, snapshotIds);

            Set<String> nextFrontier = new HashSet<>();
            for (NeighborRow row : neighbors) {
                String neighborId = row.getNeighborId();
                if (neighborId != null && !visited.contains(neighborId)) {
                    visited.add(neighborId);
                    nextFrontier.add(neighborId);
                    expandedIds.putIfAbsent(neighborId, depth);
                }
            }
            frontier = nextFrontier;
        }

        if (expandedIds.isEmpty()) return Collections.emptyList();

        List<SegmentWithMetaRow> segments =
                repo.resolveSegmentsByIds(new ArrayList<>(expandedIds.keySet()), snapshotIds);

        return segments.stream()
                .filter(seg -> seg.getId() != null && expandedIds.containsKey(seg.getId()))
                .map(seg -> new ExpandedSegmentRow(seg, expandedIds.get(seg.getId())))
                .toList();
    }
}
