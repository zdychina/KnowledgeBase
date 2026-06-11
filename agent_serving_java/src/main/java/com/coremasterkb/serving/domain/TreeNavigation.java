package com.coremasterkb.serving.domain;

import java.util.List;
import java.util.Set;

/**
 * Result of rule-based section-tree navigation (PageIndex-style "locate the chapter, then retrieve").
 *
 * <p>Carries two decoupled signals so the soft and hard behaviors can use different chapter sets:
 * <ul>
 *   <li>{@code softSections} — chapters that pass the soft dominance threshold; always used by
 *       {@code ContextAssembler} as a ranking preference (in-chapter seeds first). Empty = no bias.</li>
 *   <li>{@code hardPrefixes} — the strongly-dominant chapters used as a retrieval-time hard filter
 *       (pushed into the SQL WHERE clause). Non-empty only when {@code hardFilter} is true.</li>
 *   <li>{@code hardFilter} — true only when the navigation signal is confident enough to narrow the
 *       search at retrieval time.</li>
 * </ul>
 */
public record TreeNavigation(
        Set<String> softSections,
        List<String> hardPrefixes,
        boolean hardFilter) {

    public TreeNavigation {
        if (softSections == null) softSections = Set.of();
        if (hardPrefixes == null) hardPrefixes = List.of();
    }

    /** No navigation: full-base search, no ranking bias, no hard filter. */
    public static TreeNavigation empty() {
        return new TreeNavigation(Set.of(), List.of(), false);
    }
}
