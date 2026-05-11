package com.coremasterkb.serving.domain;

import java.util.List;

/**
 * Configuration for relation expansion during retrieval.
 *
 * @param enableRelationExpansion whether relation expansion is enabled
 * @param maxRelationDepth        maximum traversal depth
 * @param relationTypes           relation types to follow
 */
public record ExpansionConfig(
        boolean enableRelationExpansion,
        int maxRelationDepth,
        List<String> relationTypes
) {
    private static final List<String> DEFAULT_RELATION_TYPES = List.of(
            "previous", "next", "same_section", "same_parent_section",
            "section_header_of", "elaborates", "conditions", "causes",
            "results_in", "contrasts_with", "backgrounds", "enables", "parallels"
    );

    public static ExpansionConfig defaults() {
        return new ExpansionConfig(true, 2, DEFAULT_RELATION_TYPES);
    }
}
