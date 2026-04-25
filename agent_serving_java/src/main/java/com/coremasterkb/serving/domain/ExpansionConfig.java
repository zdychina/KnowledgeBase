package com.coremasterkb.serving.domain;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record ExpansionConfig(
        @JsonProperty("enable_relation_expansion") boolean enableRelationExpansion,
        @JsonProperty("max_relation_depth") int maxRelationDepth,
        @JsonProperty("relation_types") List<String> relationTypes
) {
    /** Default expansion config matching Python defaults. */
    public ExpansionConfig() {
        this(
            true,
            2,
            List.of("previous", "next", "same_section", "same_parent_section", "section_header_of")
        );
    }
}
