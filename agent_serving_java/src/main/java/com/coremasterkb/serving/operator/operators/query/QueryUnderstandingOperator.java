package com.coremasterkb.serving.operator.operators.query;

import com.coremasterkb.serving.application.QueryUnderstandingEngine;
import com.coremasterkb.serving.domain.QueryUnderstanding;
import com.coremasterkb.serving.domainpack.DomainPackReader;
import com.coremasterkb.serving.domainpack.ServingDomainProfile;
import com.coremasterkb.serving.operator.core.*;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * {@code query_understanding} — intent / entity / keyword extraction. Reuses the existing
 * {@link QueryUnderstandingEngine} (LLM-first with rule fallback) and {@link DomainPackReader}
 * for the domain profile. Neither is modified.
 *
 * <p>The {@code useLlm} param is advisory: the engine auto-selects the LLM path when the LLM
 * service is reachable and falls back to rules otherwise (no public toggle on the engine).</p>
 */
@Component
public class QueryUnderstandingOperator implements Operator {

    private static final String PARAM_SCHEMA = """
            {"type":"object","properties":{
              "useLlm":{"type":"boolean","default":true,"title":"使用 LLM 理解(advisory)"}
            }}""";

    private final QueryUnderstandingEngine engine;
    private final DomainPackReader domainPackReader;

    public QueryUnderstandingOperator(QueryUnderstandingEngine engine, DomainPackReader domainPackReader) {
        this.engine = engine;
        this.domainPackReader = domainPackReader;
    }

    @Override
    public OperatorDef definition() {
        return new OperatorDef(
                "query_understanding", "query", "查询理解",
                "抽取意图/实体/关键词/范围（LLM 优先，规则兜底）",
                List.of(SlotDecl.required("query", SlotType.STRING, "查询文本")),
                List.of(SlotDecl.required("understanding", SlotType.QUERY_UNDERSTANDING, "查询理解结果")),
                PARAM_SCHEMA,
                ErrorPolicy.FAIL_FAST);
    }

    @Override
    public SlotValues execute(SlotValues inputs, Params params, ExecContext ctx) {
        String query = inputs.getString("query");
        ServingDomainProfile profile = domainPackReader.getProfile(ctx.domain());
        QueryUnderstanding u = engine.understand(query, profile);
        return SlotValues.of("understanding", u);
    }
}
