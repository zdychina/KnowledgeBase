package com.coremasterkb.serving.operator.operators.fuse;

import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.operator.core.*;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

/**
 * {@code weighted_rrf} — weighted Reciprocal Rank Fusion. The {@code weights} param maps a
 * candidate's {@code source} (route name, e.g. {@code dense_vector} / {@code lexical_bm25}) to a
 * multiplier; unlisted sources default to 1.0.
 *
 * <p>Note: weights key on <b>source/route name</b> (the value carried on each candidate), not on
 * canvas node ids — that is the grouping the fusion actually operates over.</p>
 */
@Component
public class WeightedRrfOperator implements Operator {

    private static final String PARAM_SCHEMA = """
            {"type":"object","properties":{
              "k":{"type":"integer","minimum":1,"maximum":1000,"default":60,"title":"RRF k"},
              "weights":{"type":"object","additionalProperties":{"type":"number"},"title":"各路权重(按 source 名)"}
            }}""";

    @Override
    public OperatorDef definition() {
        return new OperatorDef(
                "weighted_rrf", "fuse", "加权 RRF",
                "加权倒数排名融合：score = Σ weight_source/(k+rank)",
                List.of(SlotDecl.required("candidates", SlotType.CANDIDATE_LIST_MULTI, "多路候选")),
                List.of(SlotDecl.required("candidates", SlotType.CANDIDATE_LIST, "融合候选")),
                PARAM_SCHEMA,
                ErrorPolicy.FAIL_FAST);
    }

    @Override
    public SlotValues execute(SlotValues inputs, Params params, ExecContext ctx) {
        List<RetrievalCandidate> merged = inputs.getCandidates("candidates");
        int k = params.getInt("k", 60);
        Map<String, Double> weights = params.getDoubleMap("weights");
        return SlotValues.of("candidates", RrfSupport.fuse(merged, k, weights));
    }
}
