package com.coremasterkb.serving.constants;

/**
 * Serving-layer constants translated from schemas/constants.py.
 */
public final class ServingConstants {

    private ServingConstants() {
        // utility class
    }

    // ---- Intent types ----
    public static final String INTENT_COMMAND_USAGE  = "command_usage";
    public static final String INTENT_TROUBLESHOOT   = "troubleshooting";
    public static final String INTENT_CONCEPT_LOOKUP = "concept_lookup";
    public static final String INTENT_PROCEDURE      = "procedure";
    public static final String INTENT_GENERAL        = "general";

    // ---- Item roles ----
    public static final String ROLE_SEED    = "seed";
    public static final String ROLE_CONTEXT = "context";
    public static final String ROLE_SUPPORT = "support";

    // ---- Item kinds ----
    public static final String KIND_RETRIEVAL_UNIT = "retrieval_unit";
    public static final String KIND_RAW_SEGMENT    = "raw_segment";

    // ---- Issue types ----
    public static final String ISSUE_NO_RESULT       = "no_result";
    public static final String ISSUE_LOW_CONFIDENCE  = "low_confidence";
    public static final String ISSUE_AMBIGUOUS_SCOPE = "ambiguous_scope";
    public static final String ISSUE_PARTIAL_CONTEXT = "partial_context";
}