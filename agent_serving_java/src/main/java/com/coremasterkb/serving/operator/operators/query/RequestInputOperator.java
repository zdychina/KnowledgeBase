package com.coremasterkb.serving.operator.operators.query;

import com.coremasterkb.serving.operator.core.*;
import com.coremasterkb.serving.operator.core.exceptions.OperatorException;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * {@code request_input} — explicit entry node that exposes the request's query as a slot, so a
 * paradigm can wire {@code input.query → query_embed.query} on the canvas instead of relying on
 * implicit entry binding. Both styles work (an unconnected {@code query} input still auto-binds);
 * this just makes the entry visible (PRD §8.4 / §12.1).
 */
@Component
public class RequestInputOperator implements Operator {

    private static final String PARAM_SCHEMA = "{\"type\":\"object\",\"properties\":{}}";

    @Override
    public OperatorDef definition() {
        return new OperatorDef(
                "request_input", "input", "查询入口",
                "把请求的 query 作为输出 slot，供起点算子显式连线",
                List.of(),
                List.of(SlotDecl.required("query", SlotType.STRING, "请求查询")),
                PARAM_SCHEMA,
                ErrorPolicy.FAIL_FAST);
    }

    @Override
    public SlotValues execute(SlotValues inputs, Params params, ExecContext ctx) {
        String query = ctx.query();
        if (query == null || query.isBlank()) {
            throw new OperatorException("request_input: no query on the request");
        }
        return SlotValues.of("query", query);
    }
}
