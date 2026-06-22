package com.coremasterkb.serving.operator.operators.rerank;

import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.operator.core.*;
import org.springframework.stereotype.Component;

import java.util.Comparator;
import java.util.List;
import java.util.stream.Collectors;

/**
 * {@code score_rerank} — score-based fallback reranker: sort by existing score descending,
 * optionally drop candidates below {@code threshold}. Always succeeds.
 */
@Component
public class ScoreRerankOperator implements Operator {

    private static final String PARAM_SCHEMA = """
            {"type":"object","properties":{
              "threshold":{"type":"number","minimum":0,"maximum":1,"default":0,"title":"分数阈值"}
            }}""";

    @Override
    public OperatorDef definition() {
        return new OperatorDef(
                "score_rerank", "rerank", "分数兜底",
                "按现有分数降序排列（永不失败）",
                List.of(SlotDecl.required("candidates", SlotType.CANDIDATE_LIST, "候选")),
                List.of(SlotDecl.required("candidates", SlotType.CANDIDATE_LIST, "排序候选")),
                PARAM_SCHEMA,
                ErrorPolicy.FAIL_FAST);
    }

    @Override
    public SlotValues execute(SlotValues inputs, Params params, ExecContext ctx) {
        List<RetrievalCandidate> candidates = inputs.getCandidates("candidates");
        double threshold = params.getDouble("threshold", 0.0);
        List<RetrievalCandidate> result = candidates.stream()
                .filter(c -> c.score() >= threshold)
                .sorted(Comparator.comparingDouble(RetrievalCandidate::score).reversed())
                .collect(Collectors.toList());
        return SlotValues.of("candidates", result);
    }
}
