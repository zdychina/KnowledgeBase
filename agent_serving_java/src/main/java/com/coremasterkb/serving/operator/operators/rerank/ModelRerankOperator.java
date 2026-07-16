package com.coremasterkb.serving.operator.operators.rerank;

import com.coremasterkb.serving.domain.EvidenceNeed;
import com.coremasterkb.serving.domain.QueryUnderstanding;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.operator.core.*;
import com.coremasterkb.serving.rerank.LlmServiceReranker;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * {@code model_rerank} — rerank candidates with the cross-encoder rerank model via llm_service.
 * Reuses the existing {@link LlmServiceReranker} bean (not modified). If the model is unavailable
 * (reranker returns null), falls back to the input order so the paradigm still yields results.
 */
@Component
public class ModelRerankOperator implements Operator {

    private static final String PARAM_SCHEMA = """
            {"type":"object","properties":{
              "topK":{"type":"integer","minimum":1,"maximum":200,"default":10,"title":"返回数量"},
              "threshold":{"type":"number","minimum":0,"maximum":1,"default":0,"title":"分数阈值"}
            }}""";

    private final LlmServiceReranker llmServiceReranker;

    public ModelRerankOperator(LlmServiceReranker llmServiceReranker) {
        this.llmServiceReranker = llmServiceReranker;
    }

    @Override
    public OperatorDef definition() {
        return new OperatorDef(
                "model_rerank", "rerank", "模型重排",
                "调用 llm_service 的 rerank 模型对候选重排序",
                List.of(
                        SlotDecl.required("candidates", SlotType.CANDIDATE_LIST, "候选"),
                        SlotDecl.required("query", SlotType.STRING, "查询文本")),
                List.of(SlotDecl.required("candidates", SlotType.CANDIDATE_LIST, "重排候选")),
                PARAM_SCHEMA,
                ErrorPolicy.FAIL_FAST);
    }

    @Override
    public SlotValues execute(SlotValues inputs, Params params, ExecContext ctx) {
        List<RetrievalCandidate> candidates = inputs.getCandidates("candidates");
        if (candidates.isEmpty()) {
            return SlotValues.of("candidates", List.of());
        }
        String query = inputs.getString("query");

        QueryUnderstanding qu = new QueryUnderstanding(
                query, "general", List.of(), List.of(), Map.of(), List.of(),
                new EvidenceNeed(List.of(), List.of(), false, false), List.of(), "operator", "medium");

        List<RetrievalCandidate> reranked = llmServiceReranker.rerank(candidates, qu);
        if (reranked == null) {
            reranked = candidates; // model unavailable → keep input order
        }

        double threshold = params.getDouble("threshold", 0.0);
        int topK = params.getInt("topK", reranked.size());
        List<RetrievalCandidate> result = reranked.stream()
                .filter(c -> c.score() >= threshold)
                .limit(topK)
                .collect(Collectors.toList());
        return SlotValues.of("candidates", result);
    }
}
