package com.coremasterkb.serving.operator.operators.rerank;

import com.coremasterkb.serving.domain.EvidenceNeed;
import com.coremasterkb.serving.domain.QueryUnderstanding;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.operator.core.*;
import com.coremasterkb.serving.rerank.LlmReranker;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * {@code llm_rerank} — listwise reranking via an LLM template. Reuses the existing
 * {@link LlmReranker} bean. Falls back to the input order when the LLM is unavailable
 * (reranker returns null).
 */
@Component
public class LlmRerankOperator implements Operator {

    private static final String PARAM_SCHEMA = """
            {"type":"object","properties":{
              "topK":{"type":"integer","minimum":1,"maximum":200,"default":10,"title":"返回数量"}
            }}""";

    private final LlmReranker llmReranker;

    public LlmRerankOperator(LlmReranker llmReranker) {
        this.llmReranker = llmReranker;
    }

    @Override
    public OperatorDef definition() {
        return new OperatorDef(
                "llm_rerank", "rerank", "LLM 重排",
                "通过 LLM 模板对候选做列表式重排",
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

        List<RetrievalCandidate> reranked = llmReranker.rerank(candidates, qu);
        if (reranked == null) {
            reranked = candidates;
        }
        int topK = params.getInt("topK", reranked.size());
        return SlotValues.of("candidates",
                reranked.stream().limit(topK).collect(Collectors.toList()));
    }
}
