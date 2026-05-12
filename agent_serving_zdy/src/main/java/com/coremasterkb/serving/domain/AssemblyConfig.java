package com.coremasterkb.serving.domain;

import java.util.List;

/**
 * Configuration for the assembly / context-building stage.
 *
 * @param sourceDrilldown   whether to drill down into sources
 * @param relationExpansion whether to expand via relations
 * @param maxItems          maximum assembled items
 * @param maxExpanded       maximum items after expansion
 * @param maxRelationDepth  maximum relation traversal depth
 * @param relationTypes     relation types to follow during expansion
 */
public record AssemblyConfig(
        boolean sourceDrilldown,
        boolean relationExpansion,
        int maxItems,
        int maxExpanded,
        int maxRelationDepth,
        List<String> relationTypes
) {
    private static final List<String> DEFAULT_RELATION_TYPES = List.of(
            "previous", "next", "same_section", "same_parent_section",
            "section_header_of", "elaborates", "conditions", "causes",
            "results_in", "contrasts_with", "backgrounds", "enables", "parallels"
    );

    public static AssemblyConfig defaults() {
        return new AssemblyConfig(true, true, 10, 10, 2, DEFAULT_RELATION_TYPES);
    }
}
