package com.coremasterkb.serving.operator.operators.fuse;

import com.coremasterkb.serving.operator.core.*;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * {@code identity} — pass candidates through unchanged. Useful as an explicit single-route
 * "fusion" placeholder so a paradigm's shape stays uniform.
 */
@Component
public class IdentityOperator implements Operator {

    private static final String PARAM_SCHEMA = "{\"type\":\"object\",\"properties\":{}}";

    @Override
    public OperatorDef definition() {
        return new OperatorDef(
                "identity", "fuse", "直通",
                "原样透传候选列表",
                List.of(SlotDecl.required("candidates", SlotType.CANDIDATE_LIST, "候选")),
                List.of(SlotDecl.required("candidates", SlotType.CANDIDATE_LIST, "候选")),
                PARAM_SCHEMA,
                ErrorPolicy.FAIL_FAST);
    }

    @Override
    public SlotValues execute(SlotValues inputs, Params params, ExecContext ctx) {
        return SlotValues.of("candidates", inputs.getCandidates("candidates"));
    }
}
