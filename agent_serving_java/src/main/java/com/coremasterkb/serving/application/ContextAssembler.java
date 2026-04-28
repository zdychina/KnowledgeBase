package com.coremasterkb.serving.application;

import com.coremasterkb.serving.constants.ServingConstants;
import com.coremasterkb.serving.domain.*;
import com.coremasterkb.serving.mapper.result.DocumentSourceRow;
import com.coremasterkb.serving.mapper.result.ExpandedSegmentRow;
import com.coremasterkb.serving.mapper.result.RelationRow;
import com.coremasterkb.serving.mapper.result.SegmentWithMetaRow;
import com.coremasterkb.serving.repository.AssetRepository;
import com.coremasterkb.serving.retrieval.GraphExpander;
import com.coremasterkb.serving.util.JsonUtils;

import java.util.*;
import java.util.stream.Collectors;

/**
 * Full 10-step context assembly pipeline.
 */
public class ContextAssembler {

    private final AssetRepository repo;
    private final GraphExpander graphExpander;

    public ContextAssembler(AssetRepository repo, GraphExpander graphExpander) {
        this.repo = repo;
        this.graphExpander = graphExpander;
    }

    public ContextPack assemble(
            String originalQuery,
            NormalizedQuery normalized,
            QueryPlan plan,
            ActiveScope scope,
            List<RetrievalCandidate> candidates
    ) {
        List<String> snapshotIds = scope.snapshotIds();

        // Step 1: Build seed items from candidates
        List<ContextItem> seedItems = buildSeedItems(candidates);

        // Step 2: Resolve source segment IDs from each candidate's metadata
        List<String> sourceSegmentIds = resolveSourceSegmentIds(candidates);

        // Step 3: Fetch source segments
        List<SegmentWithMetaRow> sourceRows =
                repo.resolveSegmentsByIds(sourceSegmentIds, snapshotIds);

        // Step 4: Build source (context) items
        List<ContextItem> sourceItems = buildSourceItems(sourceRows);

        // Step 5: Graph expansion (if enabled)
        List<ContextItem> expandedItems = new ArrayList<>();
        List<ExpandedSegmentRow> expandedRows = new ArrayList<>();
        if (plan.expansion().enableRelationExpansion() && !sourceSegmentIds.isEmpty()) {
            expandedRows = graphExpander.expand(sourceSegmentIds, plan, snapshotIds);
            expandedItems = buildExpandedItems(expandedRows);
        }

        // Step 6: Build relations from DB
        List<ContextRelation> relations =
                buildRelations(sourceRows, expandedRows, sourceSegmentIds, plan, snapshotIds);

        // Step 7: Deduplicate relations by id
        relations = deduplicateRelations(relations);

        // Step 8: Collect document IDs and build SourceRef list
        List<String> documentIds = collectDocumentIds(sourceRows, expandedRows);
        List<SourceRef> sources = buildSources(documentIds, snapshotIds);

        // Step 9: Build issues
        List<Issue> issues = buildIssues(seedItems, candidates);

        // Step 10: Assemble and truncate
        List<ContextItem> allItems = new ArrayList<>();
        allItems.addAll(seedItems);
        allItems.addAll(sourceItems);
        allItems.addAll(expandedItems);

        int maxTotal = plan.budget().maxItems() + plan.budget().maxExpanded();
        if (allItems.size() > maxTotal) {
            allItems = allItems.subList(0, maxTotal);
        }

        ContextQuery cq = new ContextQuery(
                originalQuery,
                String.join(" ", normalized.keywords()),
                normalized.intent(),
                normalized.entities(),
                normalized.scope(),
                normalized.keywords()
        );

        return new ContextPack(cq, allItems, relations, sources, issues,
                Collections.emptyList(), null);
    }

    // -------------------------------------------------------------------------
    // Step 1
    // -------------------------------------------------------------------------

    private List<ContextItem> buildSeedItems(List<RetrievalCandidate> candidates) {
        List<ContextItem> items = new ArrayList<>();
        for (RetrievalCandidate c : candidates) {
            Map<String, Object> meta = c.metadata();
            String text          = getStr(meta, "text");
            String title         = getStr(meta, "title");
            String blockType     = getStr(meta, "block_type", "unknown");
            String semRole       = getStr(meta, "semantic_role", "unknown");
            String srcSegId      = getStr(meta, "source_segment_id");
            String sourceRefsRaw = getStr(meta, "source_refs_json");
            Map<String, Object> sourceRefs = JsonUtils.safeJsonParse(sourceRefsRaw);
            items.add(new ContextItem(
                    c.retrievalUnitId(), ServingConstants.KIND_RETRIEVAL_UNIT,
                    ServingConstants.ROLE_SEED,
                    text != null ? text : "",
                    c.score(), title, blockType, semRole, srcSegId, null,
                    sourceRefs, Collections.emptyMap()));
        }
        return items;
    }

    // -------------------------------------------------------------------------
    // Step 2
    // -------------------------------------------------------------------------

    private List<String> resolveSourceSegmentIds(List<RetrievalCandidate> candidates) {
        Set<String> ids = new LinkedHashSet<>();
        for (RetrievalCandidate c : candidates) {
            Map<String, Object> meta = c.metadata();

            String srcSegId = getStr(meta, "source_segment_id");
            if (srcSegId != null && !srcSegId.isBlank()) {
                ids.add(srcSegId);
                continue;
            }

            String sourceRefsJson = getStr(meta, "source_refs_json");
            if (sourceRefsJson != null && !sourceRefsJson.isBlank()) {
                List<String> parsed = JsonUtils.parseSourceRefs(sourceRefsJson);
                if (!parsed.isEmpty()) {
                    ids.addAll(parsed);
                    continue;
                }
            }

            String targetType = getStr(meta, "target_type");
            if (targetType != null && !targetType.isBlank()) {
                String targetRefJson = getStr(meta, "target_ref_json");
                if (targetRefJson != null && !targetRefJson.isBlank()) {
                    ids.addAll(JsonUtils.parseTargetRef(targetRefJson));
                }
            }
        }
        return new ArrayList<>(ids);
    }

    // -------------------------------------------------------------------------
    // Steps 4 & 5
    // -------------------------------------------------------------------------

    private List<ContextItem> buildSourceItems(List<SegmentWithMetaRow> rows) {
        return rows.stream()
                .map(row -> segmentToItem(row, ServingConstants.ROLE_CONTEXT, null))
                .collect(Collectors.toList());
    }

    private List<ContextItem> buildExpandedItems(List<ExpandedSegmentRow> rows) {
        return rows.stream().map(expanded -> {
            String relToSeed = "expanded_depth_" + expanded.expansionDistance();
            return segmentToItem(expanded.segment(), ServingConstants.ROLE_SUPPORT, relToSeed);
        }).collect(Collectors.toList());
    }

    private ContextItem segmentToItem(SegmentWithMetaRow row, String role, String relationToSeed) {
        return new ContextItem(
                row.getId() != null ? row.getId() : "",
                ServingConstants.KIND_RAW_SEGMENT,
                role,
                row.getRawText() != null ? row.getRawText() : "",
                0.0,
                row.getSnapshotTitle(),
                row.getBlockType() != null ? row.getBlockType() : "unknown",
                row.getSemanticRole() != null ? row.getSemanticRole() : "unknown",
                row.getDocumentId(),
                relationToSeed,
                Collections.emptyMap(),
                Collections.emptyMap()
        );
    }

    // -------------------------------------------------------------------------
    // Steps 6 & 7
    // -------------------------------------------------------------------------

    private List<ContextRelation> buildRelations(
            List<SegmentWithMetaRow> sourceRows,
            List<ExpandedSegmentRow> expandedRows,
            List<String> sourceSegmentIds,
            QueryPlan plan,
            List<String> snapshotIds) {

        List<String> allSegmentIds = new ArrayList<>(sourceSegmentIds);
        expandedRows.stream()
                .map(e -> e.segment().getId())
                .filter(Objects::nonNull)
                .forEach(allSegmentIds::add);

        if (allSegmentIds.isEmpty()) return Collections.emptyList();

        List<RelationRow> relRows =
                repo.getRelationsForSegments(allSegmentIds, plan.expansion().relationTypes(), snapshotIds);

        return relRows.stream()
                .map(rr -> new ContextRelation(
                        rr.getId() != null ? rr.getId() : UUID.randomUUID().toString(),
                        rr.getFromSegmentId() != null ? rr.getFromSegmentId() : "",
                        rr.getToSegmentId()   != null ? rr.getToSegmentId()   : "",
                        rr.getRelationType()  != null ? rr.getRelationType()  : "",
                        rr.getDistance()))
                .collect(Collectors.toList());
    }

    private List<ContextRelation> deduplicateRelations(List<ContextRelation> relations) {
        Map<String, ContextRelation> seen = new LinkedHashMap<>();
        for (ContextRelation r : relations) {
            seen.putIfAbsent(r.id(), r);
        }
        return new ArrayList<>(seen.values());
    }

    // -------------------------------------------------------------------------
    // Step 8
    // -------------------------------------------------------------------------

    private List<String> collectDocumentIds(
            List<SegmentWithMetaRow> sourceRows,
            List<ExpandedSegmentRow> expandedRows) {
        Set<String> ids = new LinkedHashSet<>();
        sourceRows.stream()
                .map(SegmentWithMetaRow::getDocumentId)
                .filter(Objects::nonNull)
                .forEach(ids::add);
        expandedRows.stream()
                .map(e -> e.segment().getDocumentId())
                .filter(Objects::nonNull)
                .forEach(ids::add);
        return new ArrayList<>(ids);
    }

    private List<SourceRef> buildSources(List<String> documentIds, List<String> snapshotIds) {
        if (documentIds.isEmpty()) return Collections.emptyList();
        List<DocumentSourceRow> rows = repo.getDocumentSources(documentIds, snapshotIds);
        return rows.stream().map(row -> {
            Map<String, Object> scope = JsonUtils.safeJsonParse(row.getScopeJson());
            return new SourceRef(
                    row.getId() != null ? row.getId() : "",
                    row.getDocumentKey() != null ? row.getDocumentKey() : "",
                    row.getTitle(),
                    row.getRelativePath(),
                    scope,
                    Collections.emptyMap());
        }).collect(Collectors.toList());
    }

    // -------------------------------------------------------------------------
    // Step 9
    // -------------------------------------------------------------------------

    private List<Issue> buildIssues(
            List<ContextItem> seedItems, List<RetrievalCandidate> candidates) {
        List<Issue> issues = new ArrayList<>();
        if (seedItems.isEmpty()) {
            issues.add(new Issue(ServingConstants.ISSUE_NO_RESULT,
                    "No retrieval results found for the query."));
            return issues;
        }
        boolean allLowConfidence = candidates.stream().allMatch(c -> c.score() < 0.1);
        if (allLowConfidence) {
            issues.add(new Issue(ServingConstants.ISSUE_LOW_CONFIDENCE,
                    "All retrieved results have very low confidence scores."));
        }
        return issues;
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    private String getStr(Map<String, Object> map, String key) {
        Object val = map.get(key);
        return val instanceof String s ? s : null;
    }

    private String getStr(Map<String, Object> map, String key, String defaultVal) {
        String v = getStr(map, key);
        return v != null ? v : defaultVal;
    }
}
