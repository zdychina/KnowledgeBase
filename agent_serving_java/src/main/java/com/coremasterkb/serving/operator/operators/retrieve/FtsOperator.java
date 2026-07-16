package com.coremasterkb.serving.operator.operators.retrieve;

import com.coremasterkb.serving.domain.ActiveScope;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.RetrievalQuery;
import com.coremasterkb.serving.operator.core.*;
import com.coremasterkb.serving.retrieval.FtsRetriever;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

/**
 * {@code fts} — full-text lexical retrieval with the existing three-level degradation
 * (tsvector → trigram → LIKE). Reuses the existing {@link FtsRetriever} bean (not modified),
 * which carries the tuned jieba tokenization and scope-pushdown SQL.
 */
@Component
public class FtsOperator implements Operator {

    private static final String PARAM_SCHEMA = """
            {"type":"object","properties":{
              "topK":{"type":"integer","minimum":1,"maximum":200,"default":20,"title":"返回数量"}
            }}""";

    private final FtsRetriever ftsRetriever;

    public FtsOperator(FtsRetriever ftsRetriever) {
        this.ftsRetriever = ftsRetriever;
    }

    @Override
    public OperatorDef definition() {
        return new OperatorDef(
                "fts", "retrieve", "全文检索",
                "PostgreSQL 全文检索（tsvector→trigram→LIKE 三级降级）",
                List.of(
                        SlotDecl.required("query", SlotType.STRING, "查询文本"),
                        SlotDecl.required("scope", SlotType.SCOPE, "检索范围(snapshotIds)")),
                List.of(SlotDecl.required("candidates", SlotType.CANDIDATE_LIST, "检索候选")),
                PARAM_SCHEMA,
                ErrorPolicy.SKIP_WITH_EMPTY);
    }

    @Override
    public SlotValues execute(SlotValues inputs, Params params, ExecContext ctx) {
        String query = inputs.getString("query");
        ActiveScope scope = inputs.getScope("scope");
        if (query == null || query.isBlank() || scope == null || scope.snapshotIds().isEmpty()) {
            return SlotValues.of("candidates", List.of());
        }
        int topK = params.getInt("topK", 20);

        // No keywords/entities/facet-scope at the operator boundary: the retriever tokenizes
        // originalQuery itself, and snapshotIds provide scoping.
        RetrievalQuery rq = new RetrievalQuery(
                query, List.of(), List.of(), null, List.of(), "general", Map.of(), List.of());

        List<RetrievalCandidate> candidates = ftsRetriever.retrieve(rq, scope.snapshotIds(), topK);
        return SlotValues.of("candidates", candidates);
    }
}
