package com.coremasterkb.serving.domain;

import java.util.List;

/**
 * Describes what kinds of evidence the caller expects for a given query.
 *
 * @param preferredRoles   preferred evidence roles (e.g. "direct_answer", "support"); defaults to empty
 * @param preferredBlocks  preferred block types; defaults to empty
 * @param needsComparison  whether a comparison-style answer is expected
 * @param needsCitation    whether citation / source references are required
 */
public record EvidenceNeed(
        List<String> preferredRoles,
        List<String> preferredBlocks,
        boolean needsComparison,
        boolean needsCitation
) {
    public EvidenceNeed {
        if (preferredRoles == null) preferredRoles = List.of();
        if (preferredBlocks == null) preferredBlocks = List.of();
    }

    public static EvidenceNeed empty() {
        return new EvidenceNeed(List.of(), List.of(), false, false);
    }
}
