package com.coremasterkb.serving.operator.core;

/**
 * A pluggable retrieval operator: the smallest composable unit of the operator DAG.
 *
 * <p>Operators are <b>stateless</b> Spring singletons. All per-request state arrives via
 * {@code inputs}, {@code params}, and {@code ctx}; nothing is stored on the instance. This makes
 * operator beans thread-safe and freely parallelisable by the executor.</p>
 */
public interface Operator {

    /** Declares this operator's type, slots, param schema, and error policy. Collected at startup. */
    OperatorDef definition();

    /**
     * Execute the operator.
     *
     * @param inputs upstream slot values bound by the engine (validated against input slot types)
     * @param params this node's params (already schema-validated at compile time)
     * @param ctx    per-execution shared context (domain, channel, attributes, trace)
     * @return output slot values (keys must match this operator's output slot names)
     */
    SlotValues execute(SlotValues inputs, Params params, ExecContext ctx);
}
