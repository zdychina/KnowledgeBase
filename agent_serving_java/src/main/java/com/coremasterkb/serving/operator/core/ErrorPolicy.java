package com.coremasterkb.serving.operator.core;

/**
 * How the DAG executor treats an exception thrown by an operator node.
 *
 * <ul>
 *   <li>{@link #FAIL_FAST} — node failure aborts the whole paradigm execution (default for
 *       rerank/assemble/output operators).</li>
 *   <li>{@link #SKIP_WITH_EMPTY} — node failure yields empty outputs (empty candidate list),
 *       downstream continues (default for retrieve operators, so one failed route does not
 *       break a multi-route fusion).</li>
 *   <li>{@link #FALLBACK} — the operator handles degradation internally (e.g. FTS
 *       tsvector→trigram→LIKE); if it still throws, the executor treats it as fail-fast.</li>
 * </ul>
 */
public enum ErrorPolicy {
    FAIL_FAST,
    SKIP_WITH_EMPTY,
    FALLBACK
}
