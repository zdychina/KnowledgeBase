package com.coremasterkb.serving.application;

import com.coremasterkb.serving.domain.*;
import com.coremasterkb.serving.mapper.result.DocumentSourceRow;
import com.coremasterkb.serving.mapper.result.ExpandedSegmentRow;
import com.coremasterkb.serving.mapper.result.RelationRow;
import com.coremasterkb.serving.mapper.result.SegmentWithMetaRow;
import com.coremasterkb.serving.repository.AssetRepository;
import com.coremasterkb.serving.retrieval.GraphExpander;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.*;

/**
 * Builds ContextPack from retrieval results.
 *
 * <p>Pipeline: seed items &rarr; source drill-down &rarr; graph expansion &rarr;
 * deduplicate &rarr; build source refs &rarr; build issues &rarr; truncate &rarr;
 * build ContextQuery &rarr; pack into ContextPack.
 * Matches Python's ContextAssembler behavior.
 */
@Component
public class ContextAssembler {

    private static final Logger log = LoggerFactory.getLogger(ContextAssembler.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    // Issue type constants (match Python)
    private static final String ISSUE_NO_RESULT = "no_result";
    private static final String ISSUE_LOW_CONFIDENCE = "low_confidence";

    // Kind/role constants
    private static final String KIND_RETRIEVAL_UNIT = "retrieval_unit";
    private static final String KIND_RAW_SEGMENT = "raw_segment";
    private static final String ROLE_SEED = "seed";
    private static final String ROLE_CONTEXT = "context";
    private static final String ROLE_SUPPORT = "support";

    // RST relation type -> evidence role mapping for expansion
    private static final Map<String, String> RST_ROLE_MAP = Map.ofEntries(
            Map.entry("elaborates", "support"),
            Map.entry("conditions", "support"),
            Map.entry("causes", "support"),
            Map.entry("results_in", "support"),
            Map.entry("backgrounds", "background"),
            Map.entry("enables", "support"),
            Map.entry("parallels", "context"),
            Map.entry("contrasts_with", "contrast"),
            Map.entry("previous", "context"),
            Map.entry("next", "context"),
            Map.entry("same_section", "context"),
            Map.entry("same_parent_section", "context"),
            Map.entry("section_header_of", "context")
    );

    private final AssetRepository repo;
    private final GraphExpander graphExpander;

    public ContextAssembler(AssetRepository repo, GraphExpander graphExpander) {
        this.repo = repo;
        this.graphExpander = graphExpander;
    }

    /**
     * Full assembly pipeline: seed -> source drill-down -> expansion -> pack.
     *
     * @param query         original user query
     * @param understanding query understanding result
     * @param scope         active scope with snapshot IDs
     * @param candidates    ranked retrieval candidates
     * @param routePlan     route plan controlling assembly behavior
     * @return assembled ContextPack
     */
    public ContextPack assemble(
            String query,
            QueryUnderstanding understanding,
            ActiveScope scope,
            List<RetrievalCandidate> candidates,
            RetrievalRoutePlan routePlan) {

        if (candidates == null) candidates = List.of();
        if (scope == null) scope = new ActiveScope("", "", List.of(), Map.of());
        if (routePlan == null) routePlan = new RetrievalRoutePlan(List.of(), Map.of(), null, null, null, null);

        // 1. Build seed items from retrieval candidates
        List<ContextItem> seedItems = buildSeedItems(candidates, understanding);

        // 2. Resolve source segment IDs from candidates
        List<String> allSourceSegmentIds = new ArrayList<>();
        for (var candidate : candidates) {
            allSourceSegmentIds.addAll(resolveCandidateSources(candidate));
        }

        // Deduplicate segment IDs
        Set<String> seenSegs = new LinkedHashSet<>();
        List<String> uniqueSegIds = new ArrayList<>();
        for (String sid : allSourceSegmentIds) {
            if (seenSegs.add(sid)) {
                uniqueSegIds.add(sid);
            }
        }

        // 3. Fetch source segments
        List<SegmentWithMetaRow> sourceSegments;
        if (!uniqueSegIds.isEmpty() && scope.snapshotIds() != null && !scope.snapshotIds().isEmpty()) {
            sourceSegments = repo.resolveSegmentsByIds(uniqueSegIds, scope.snapshotIds());
        } else {
            sourceSegments = List.of();
        }
        Map<String, SegmentWithMetaRow> sourceSegMap = new LinkedHashMap<>();
        for (var seg : sourceSegments) {
            if (seg.getId() != null) {
                sourceSegMap.put(seg.getId(), seg);
            }
        }
        List<ContextItem> sourceItems = buildSourceItems(sourceSegments);

        // 4. Graph expansion if enabled
        List<ContextItem> expandedItems = new ArrayList<>();
        List<ContextRelation> relationItems = new ArrayList<>();

        boolean expansionEnabled = routePlan.assembly() != null && routePlan.assembly().relationExpansion();
        if (expansionEnabled && !uniqueSegIds.isEmpty() && scope.snapshotIds() != null && !scope.snapshotIds().isEmpty()) {
            int maxDepth = routePlan.assembly().maxRelationDepth();
            int maxResults = routePlan.assembly().maxExpanded();
            List<String> relationTypes = routePlan.assembly().relationTypes();

            List<ExpandedSegmentRow> expansions = graphExpander.expand(
                    uniqueSegIds, maxDepth, relationTypes, maxResults, scope.snapshotIds());

            expandedItems = buildExpandedItems(expansions);

            // Build expansion relations
            for (var exp : expansions) {
                SegmentWithMetaRow seg = exp.segment();
                if (seg != null && seg.getId() != null) {
                    // Find which seed this expansion came from (approximate: use first seed)
                    String fromId = uniqueSegIds.isEmpty() ? "" : uniqueSegIds.get(0);
                    relationItems.add(new ContextRelation(
                            "rel-" + fromId + "-" + seg.getId(),
                            fromId,
                            seg.getId(),
                            "expansion",
                            exp.expansionDistance()
                    ));
                }
            }
        }

        // 5. Fetch direct relations
        if (!uniqueSegIds.isEmpty()) {
            List<String> relTypes = routePlan.assembly() != null ? routePlan.assembly().relationTypes() : null;
            List<RelationRow> directRelations = repo.getRelationsForSegments(uniqueSegIds, relTypes,
                    scope.snapshotIds());
            for (var rel : directRelations) {
                String rid = rel.getId() != null ? rel.getId() : UUID.randomUUID().toString();
                relationItems.add(new ContextRelation(
                        rid,
                        rel.getFromSegmentId(),
                        rel.getToSegmentId(),
                        rel.getRelationType(),
                        0
                ));
            }
        }

        // Deduplicate relations
        Set<String> seenRels = new HashSet<>();
        List<ContextRelation> uniqueRelations = new ArrayList<>();
        for (var r : relationItems) {
            if (seenRels.add(r.id())) {
                uniqueRelations.add(r);
            }
        }

        // 6. Build source references
        Set<String> documentIds = new LinkedHashSet<>();
        for (var seg : sourceSegments) {
            if (seg.getDocumentId() != null && !seg.getDocumentId().isBlank()) {
                documentIds.add(seg.getDocumentId());
            }
        }
        List<DocumentSourceRow> docSources = !documentIds.isEmpty()
                ? repo.getDocumentSources(new ArrayList<>(documentIds), scope.snapshotIds())
                : List.of();
        List<SourceRef> sources = buildSources(docSources);

        // 7. Build issues
        List<Issue> issues = buildIssues(seedItems, understanding);

        // 8. Assemble final pack — combine and truncate
        List<ContextItem> allItems = new ArrayList<>(seedItems);
        allItems.addAll(sourceItems);
        allItems.addAll(expandedItems);

        int maxItems = routePlan.assembly().maxItems() + routePlan.assembly().maxExpanded();
        if (allItems.size() > maxItems) {
            allItems = allItems.subList(0, maxItems);
        }

        // Filter relations: only keep edges where both endpoints exist in final items
        Set<String> itemIds = new HashSet<>();
        for (var item : allItems) {
            itemIds.add(item.id());
        }
        List<ContextRelation> filteredRelations = new ArrayList<>();
        for (var r : uniqueRelations) {
            if (itemIds.contains(r.fromId()) && itemIds.contains(r.toId())) {
                filteredRelations.add(r);
            }
        }

        // 9. Build ContextQuery from understanding
        ContextQuery contextQuery;
        if (understanding != null) {
            contextQuery = new ContextQuery(
                    query,
                    formatUnderstanding(understanding),
                    understanding.intent(),
                    understanding.entities(),
                    understanding.scope(),
                    understanding.keywords()
            );
        } else {
            contextQuery = new ContextQuery(query, "", null, null, null, null);
        }

        // 10. Build evidence groups and suggestions
        List<EvidenceGroup> evidenceGroups = buildEvidenceGroups(allItems, filteredRelations);
        List<String> suggestions = buildSuggestions(issues);

        return new ContextPack(
                contextQuery,
                allItems,
                filteredRelations,
                sources,
                evidenceGroups,
                issues,
                suggestions,
                Map.of()
        );
    }

    // =========================================================================
    // Seed item building
    // =========================================================================

    private List<ContextItem> buildSeedItems(
            List<RetrievalCandidate> candidates,
            QueryUnderstanding understanding) {
        List<ContextItem> items = new ArrayList<>();
        for (var c : candidates) {
            Map<String, Object> citation = buildCitation(c);

            List<String> routeSources = List.of();
            if (c.scoreChain() != null && c.scoreChain().routeSources() != null) {
                routeSources = c.scoreChain().routeSources();
            }

            items.add(new ContextItem(
                    c.retrievalUnitId(),
                    KIND_RETRIEVAL_UNIT,
                    ROLE_SEED,
                    getMetadataString(c.metadata(), "text", ""),
                    c.score(),
                    getMetadataString(c.metadata(), "title", null),
                    getMetadataString(c.metadata(), "block_type", "unknown"),
                    getMetadataString(c.metadata(), "semantic_role", "unknown"),
                    null,
                    null,
                    safeJsonParse(getMetadataString(c.metadata(), "source_refs_json", "{}")),
                    c.metadata(),
                    routeSources,
                    c.scoreChain(),
                    "",
                    citation
            ));
        }
        return items;
    }

    private Map<String, Object> buildCitation(RetrievalCandidate candidate) {
        Map<String, Object> citation = new LinkedHashMap<>();
        Map<String, Object> sourceRefs = safeJsonParse(getMetadataString(candidate.metadata(), "source_refs_json", "{}"));

        @SuppressWarnings("unchecked")
        List<String> rawSegIds = (List<String>) sourceRefs.get("raw_segment_ids");
        if (rawSegIds != null && !rawSegIds.isEmpty()) {
            citation.put("raw_segment_ids", rawSegIds);
        }

        String title = getMetadataString(candidate.metadata(), "title", null);
        if (title != null) {
            citation.put("section", title);
        }

        String docSnapshotId = getMetadataString(candidate.metadata(), "document_snapshot_id", null);
        if (docSnapshotId != null) {
            citation.put("document_snapshot_id", docSnapshotId);
        }

        return citation;
    }

    // =========================================================================
    // Source resolution
    // =========================================================================

    private List<String> resolveCandidateSources(RetrievalCandidate candidate) {
        // Priority 1: source_segment_id
        String segId = getMetadataString(candidate.metadata(), "source_segment_id", null);
        if (segId != null && !segId.isBlank()) {
            return List.of(segId);
        }

        // Priority 2: source_refs_json
        String sourceRefsJson = getMetadataString(candidate.metadata(), "source_refs_json", "{}");
        List<String> segIds = parseSourceRefs(sourceRefsJson);
        if (!segIds.isEmpty()) {
            return segIds;
        }

        // Priority 3: target_ref_json
        String targetType = getMetadataString(candidate.metadata(), "target_type", "");
        String targetRefJson = getMetadataString(candidate.metadata(), "target_ref_json", "{}");
        if (!targetType.isBlank() && !targetRefJson.equals("{}")) {
            segIds = parseSourceRefs(targetRefJson);
            if (!segIds.isEmpty()) {
                return segIds;
            }
        }

        return List.of();
    }

    // =========================================================================
    // Context item building
    // =========================================================================

    private List<ContextItem> buildSourceItems(List<SegmentWithMetaRow> segments) {
        List<ContextItem> items = new ArrayList<>();
        for (var seg : segments) {
            items.add(new ContextItem(
                    seg.getId(),
                    KIND_RAW_SEGMENT,
                    ROLE_CONTEXT,
                    seg.getRawText() != null ? seg.getRawText() : "",
                    0.0,
                    seg.getSnapshotTitle(),
                    seg.getBlockType() != null ? seg.getBlockType() : "unknown",
                    seg.getSemanticRole() != null ? seg.getSemanticRole() : "unknown",
                    seg.getDocumentId(),
                    null,
                    Map.of(),
                    Map.of(),
                    List.of(),
                    null,
                    "",
                    Map.of()
            ));
        }
        return items;
    }

    private List<ContextItem> buildExpandedItems(List<ExpandedSegmentRow> expansions) {
        List<ContextItem> items = new ArrayList<>();
        for (var exp : expansions) {
            SegmentWithMetaRow seg = exp.segment();
            // For expanded items, use a default relation type since ExpandedSegmentRow doesn't carry it
            String evidenceRole = "background";

            items.add(new ContextItem(
                    seg.getId(),
                    KIND_RAW_SEGMENT,
                    ROLE_SUPPORT,
                    seg.getRawText() != null ? seg.getRawText() : "",
                    0.0,
                    seg.getSnapshotTitle(),
                    seg.getBlockType() != null ? seg.getBlockType() : "unknown",
                    seg.getSemanticRole() != null ? seg.getSemanticRole() : "unknown",
                    seg.getDocumentId(),
                    "expansion",
                    Map.of(),
                    Map.of(),
                    List.of(),
                    null,
                    evidenceRole,
                    Map.of()
            ));
        }
        return items;
    }

    // =========================================================================
    // Source refs building
    // =========================================================================

    private List<SourceRef> buildSources(List<DocumentSourceRow> docs) {
        Set<String> seen = new HashSet<>();
        List<SourceRef> sources = new ArrayList<>();
        for (var doc : docs) {
            String docId = doc.getId();
            if (docId == null || seen.contains(docId)) continue;
            seen.add(docId);

            sources.add(new SourceRef(
                    docId,
                    doc.getDocumentKey() != null ? doc.getDocumentKey() : "",
                    doc.getTitle(),
                    doc.getRelativePath(),
                    safeJsonParse(doc.getScopeJson() != null ? doc.getScopeJson() : "{}"),
                    Map.of()
            ));
        }
        return sources;
    }

    // =========================================================================
    // Issues and suggestions
    // =========================================================================

    private List<Issue> buildIssues(List<ContextItem> items, QueryUnderstanding understanding) {
        List<Issue> issues = new ArrayList<>();
        String queryText = understanding != null ? understanding.originalQuery() : "";

        if (items.isEmpty()) {
            issues.add(new Issue(
                    ISSUE_NO_RESULT,
                    "未找到相关内容",
                    Map.of("query", queryText)
            ));
        } else if (items.stream().allMatch(item -> item.score() < 0.1)) {
            double topScore = items.stream().mapToDouble(ContextItem::score).max().orElse(0.0);
            issues.add(new Issue(
                    ISSUE_LOW_CONFIDENCE,
                    "检索结果置信度较低",
                    Map.of("top_score", topScore)
            ));
        }

        return issues;
    }

    private List<String> buildSuggestions(List<Issue> issues) {
        List<String> suggestions = new ArrayList<>();
        for (var issue : issues) {
            if (ISSUE_NO_RESULT.equals(issue.type())) {
                suggestions.add("尝试使用更通用的关键词");
            } else if (ISSUE_LOW_CONFIDENCE.equals(issue.type())) {
                suggestions.add("尝试更精确的描述或添加产品/版本约束");
            }
        }
        return suggestions;
    }

    // =========================================================================
    // Evidence groups
    // =========================================================================

    private List<EvidenceGroup> buildEvidenceGroups(
            List<ContextItem> items,
            List<ContextRelation> relations) {
        Map<String, List<String>> snapshotItems = new LinkedHashMap<>();
        for (var item : items) {
            Object snapId = item.metadata().get("document_snapshot_id");
            if (snapId instanceof String s && !s.isBlank()) {
                snapshotItems.computeIfAbsent(s, k -> new ArrayList<>()).add(item.id());
            }
        }

        if (snapshotItems.isEmpty()) {
            return List.of();
        }

        List<EvidenceGroup> groups = new ArrayList<>();
        for (var entry : snapshotItems.entrySet()) {
            Set<String> itemIdSet = new HashSet<>(entry.getValue());
            List<String> groupRelIds = new ArrayList<>();
            for (var r : relations) {
                if (itemIdSet.contains(r.fromId()) || itemIdSet.contains(r.toId())) {
                    groupRelIds.add(r.id());
                }
            }
            groups.add(new EvidenceGroup(entry.getKey(), entry.getValue(), groupRelIds));
        }
        return groups;
    }

    // =========================================================================
    // Formatting helpers
    // =========================================================================

    private String formatUnderstanding(QueryUnderstanding understanding) {
        List<String> parts = new ArrayList<>();
        parts.add("intent=" + understanding.intent());
        for (var e : understanding.entities()) {
            parts.add(e.type() + "=" + e.name());
        }
        parts.addAll(understanding.keywords());
        return String.join(" ", parts);
    }

    // =========================================================================
    // JSON parsing utilities
    // =========================================================================

    private Map<String, Object> safeJsonParse(String json) {
        if (json == null || json.isBlank() || "{}".equals(json)) {
            return Map.of();
        }
        try {
            return MAPPER.readValue(json, new TypeReference<LinkedHashMap<String, Object>>() {});
        } catch (Exception e) {
            return Map.of();
        }
    }

    @SuppressWarnings("unchecked")
    private List<String> parseSourceRefs(String json) {
        Map<String, Object> parsed = safeJsonParse(json);
        Object rawSegIds = parsed.get("raw_segment_ids");
        if (rawSegIds instanceof List<?> list) {
            List<String> result = new ArrayList<>();
            for (Object item : list) {
                if (item != null) result.add(String.valueOf(item));
            }
            return result;
        }
        return List.of();
    }

    // =========================================================================
    // Metadata helpers
    // =========================================================================

    private String getMetadataString(Map<String, Object> metadata, String key, String defaultValue) {
        Object value = metadata.get(key);
        if (value == null) return defaultValue;
        String str = String.valueOf(value);
        return str.isBlank() ? defaultValue : str;
    }
}
