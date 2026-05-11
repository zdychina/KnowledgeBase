package com.coremasterkb.serving.domain;

import java.util.Map;

/**
 * Central constants for the serving layer.
 */
public final class ServingConstants {

    private ServingConstants() {
        // prevent instantiation
    }

    // ---- Intent constants ----
    public static final String INTENT_COMMAND_USAGE = "command_usage";
    public static final String INTENT_TROUBLESHOOT = "troubleshooting";
    public static final String INTENT_CONCEPT_LOOKUP = "concept_lookup";
    public static final String INTENT_PROCEDURE = "procedure";
    public static final String INTENT_GENERAL = "general";
    public static final String INTENT_COMPARISON = "comparison";
    public static final String INTENT_NAVIGATIONAL = "navigational";

    // ---- Route constants ----
    public static final String ROUTE_LEXICAL_BM25 = "lexical_bm25";
    public static final String ROUTE_ENTITY_EXACT = "entity_exact";
    public static final String ROUTE_DENSE_VECTOR = "dense_vector";

    // ---- Role constants ----
    public static final String ROLE_SEED = "seed";
    public static final String ROLE_CONTEXT = "context";
    public static final String ROLE_SUPPORT = "support";

    // ---- Kind constants ----
    public static final String KIND_RETRIEVAL_UNIT = "retrieval_unit";
    public static final String KIND_RAW_SEGMENT = "raw_segment";

    /**
     * Mapping from LLM-produced intent labels to internal canonical intents.
     * Includes idempotent self-mappings so that already-canonical values pass through unchanged.
     */
    public static final Map<String, String> LLM_INTENT_TO_INTERNAL = Map.ofEntries(
            // LLM intent -> internal intent
            Map.entry("conceptual", "concept_lookup"),
            Map.entry("factoid", "general"),
            Map.entry("procedural", "procedure"),
            Map.entry("comparative", "comparison"),
            Map.entry("troubleshooting", "troubleshooting"),
            Map.entry("navigational", "general"),
            Map.entry("general", "general"),
            // idempotent self-mappings
            Map.entry("concept_lookup", "concept_lookup"),
            Map.entry("procedure", "procedure"),
            Map.entry("comparison", "comparison"),
            Map.entry("command_usage", "command_usage")
    );
}
