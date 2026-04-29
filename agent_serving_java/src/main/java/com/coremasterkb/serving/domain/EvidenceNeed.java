package com.coremasterkb.serving.domain;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.Collections;
import java.util.List;

public record EvidenceNeed(
        @JsonProperty("preferred_roles")   List<String> preferredRoles,
        @JsonProperty("preferred_blocks")  List<String> preferredBlocks,
        @JsonProperty("needs_comparison")  boolean needsComparison,
        @JsonProperty("needs_citation")    boolean needsCitation
) {
    public EvidenceNeed {
        if (preferredRoles  == null) preferredRoles  = Collections.emptyList();
        if (preferredBlocks == null) preferredBlocks = Collections.emptyList();
    }

    public EvidenceNeed() {
        this(Collections.emptyList(), Collections.emptyList(), false, false);
    }
}
