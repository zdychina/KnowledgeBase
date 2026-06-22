package com.coremasterkb.serving.domain;

import java.util.List;
import java.util.Map;

/**
 * The assembled context pack delivered to the caller.
 *
 * @param query          the context query that produced this pack
 * @param items          assembled context items; defaults to empty list
 * @param relations      relations between items; defaults to empty list
 * @param sources        referenced source documents; defaults to empty list
 * @param evidenceGroups evidence grouped by snapshot; defaults to empty list
 * @param issues         issues encountered during assembly; defaults to empty list
 * @param suggestions    suggestions for improving the query; defaults to empty list
 * @param debug          debug information (populated when debug=true); defaults to empty map
 */
public record ContextPack(
        ContextQuery query,
        List<ContextItem> items,
        List<ContextRelation> relations,
        List<SourceRef> sources,
        List<EvidenceGroup> evidenceGroups,
        List<Issue> issues,
        List<String> suggestions,
        Map<String, Object> debug
) {
    public ContextPack {
        if (items == null) items = List.of();
        if (relations == null) relations = List.of();
        if (sources == null) sources = List.of();
        if (evidenceGroups == null) evidenceGroups = List.of();
        if (issues == null) issues = List.of();
        if (suggestions == null) suggestions = List.of();
        if (debug == null) debug = Map.of();
    }
}
