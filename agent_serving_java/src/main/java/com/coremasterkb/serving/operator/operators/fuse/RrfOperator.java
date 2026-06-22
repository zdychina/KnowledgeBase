package com.coremasterkb.serving.operator.operators.fuse;

import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.operator.core.*;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * {@code rrf} — Reciprocal Rank Fusion of multiple candidate lists (variadic input).
 * Equal weight per source route.
 */
@Component
public class RrfOperator implements Operator {

    private static final String PARAM_SCHEMA = """
            {"type":"object","properties":{
              "k":{"type":"integer","minimum":1,"maximum":1000,"default":60,"title":"RRF k"}
            }}""";

    @Override
    public OperatorDef definition() {
        return new OperatorDef(
                "rrf", "fuse", "RRF 融合",
                "倒数排名融合，多路候选按 1/(k+rank) 求和",
                List.of(SlotDecl.required("candidates", SlotType.CANDIDATE_LIST_MULTI, "多路候选")),
                List.of(SlotDecl.required("candidates", SlotType.CANDIDATE_LIST, "融合候选")),
                PARAM_SCHEMA,
                ErrorPolicy.FAIL_FAST);
    }

    @Override
    public SlotValues execute(SlotValues inputs, Params params, ExecContext ctx) {
        List<RetrievalCandidate> merged = inputs.getCandidates("candidates");
        int k = params.getInt("k", 60);
        return SlotValues.of("candidates", RrfSupport.fuse(merged, k, null));
    }
}
