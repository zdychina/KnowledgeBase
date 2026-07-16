package com.coremasterkb.serving.operator.operators.output;

import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.operator.core.*;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * {@code collect} — terminal output operator for test paradigms. Returns the candidate list
 * (id / score / scoreChain / source / metadata), truncated to {@code maxItems}, ready for
 * recall/precision/MRR/NDCG scoring by the test system.
 */
@Component
public class CollectOperator implements Operator {

    private static final String PARAM_SCHEMA = """
            {"type":"object","properties":{
              "maxItems":{"type":"integer","minimum":1,"maximum":500,"default":20,"title":"最大返回数"}
            }}""";

    @Override
    public OperatorDef definition() {
        return new OperatorDef(
                "collect", "output", "收集候选（测试用）",
                "终点算子：输出候选列表，供测试系统计算检索指标",
                List.of(SlotDecl.required("candidates", SlotType.CANDIDATE_LIST, "候选")),
                List.of(SlotDecl.required("candidates", SlotType.CANDIDATE_LIST, "候选(终点)")),
                PARAM_SCHEMA,
                ErrorPolicy.FAIL_FAST);
    }

    @Override
    public SlotValues execute(SlotValues inputs, Params params, ExecContext ctx) {
        List<RetrievalCandidate> candidates = inputs.getCandidates("candidates");
        int maxItems = params.getInt("maxItems", 20);
        if (candidates.size() > maxItems) {
            candidates = candidates.subList(0, maxItems);
        }
        return SlotValues.of("candidates", List.copyOf(candidates));
    }
}
