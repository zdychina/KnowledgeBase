package com.coremasterkb.serving.evidence;

import com.coremasterkb.serving.domain.ContextItem;
import com.coremasterkb.serving.domain.QueryUnderstanding;

import java.util.*;
import java.util.stream.Collectors;

/**
 * Classifies context items into evidence roles: direct_answer, support, contrast, background, missing.
 * Aligned with Python evidence/role_classifier.py -- NOT integrated in main pipeline yet.
 */
public class EvidenceRoleClassifier {

    private static final double HIGH_SCORE_THRESHOLD = 0.7;
    private static final double MEDIUM_SCORE_THRESHOLD = 0.4;

    public List<ContextItem> classify(List<ContextItem> items, QueryUnderstanding understanding) {
        if (items == null || items.isEmpty()) return List.of();

        return items.stream()
                .map(item -> classifyItem(item, understanding))
                .collect(Collectors.toList());
    }

    private ContextItem classifyItem(ContextItem item, QueryUnderstanding understanding) {
        String role = determineRole(item, understanding);
        return new ContextItem(
                item.id(), item.kind(), item.role(), item.text(), item.score(),
                item.title(), item.blockType(), item.semanticRole(), item.sourceId(),
                item.relationToSeed(), item.sourceRefs(), item.metadata(),
                item.routeSources(), item.scoreChain(), role, item.citation()
        );
    }

    private String determineRole(ContextItem item, QueryUnderstanding understanding) {
        double score = item.score();

        if ("seed".equals(item.relationToSeed())) {
            if (score >= HIGH_SCORE_THRESHOLD) return "direct_answer";
            if (score >= MEDIUM_SCORE_THRESHOLD) return "support";
            return "background";
        }

        if (item.relationToSeed() != null && !item.relationToSeed().isEmpty()) {
            String rel = item.relationToSeed();
            if ("contrasts_with".equals(rel)) return "contrast";
            if (Set.of("elaborates", "conditions", "causes", "results_in").contains(rel)) return "support";
            return "background";
        }

        if (score >= MEDIUM_SCORE_THRESHOLD) return "support";
        return "background";
    }
}
