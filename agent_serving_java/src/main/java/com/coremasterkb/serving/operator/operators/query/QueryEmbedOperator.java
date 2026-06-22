package com.coremasterkb.serving.operator.operators.query;

import com.coremasterkb.serving.infrastructure.EmbeddingClient;
import com.coremasterkb.serving.operator.core.*;
import com.coremasterkb.serving.operator.core.exceptions.OperatorException;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * {@code query_embed} — embed the query string into a vector via the shared embedding service.
 * Reuses the existing {@link EmbeddingClient} (model/dimensions managed by llm_service).
 */
@Component
public class QueryEmbedOperator implements Operator {

    private static final String PARAM_SCHEMA = "{\"type\":\"object\",\"properties\":{}}";

    private final EmbeddingClient embeddingClient;

    public QueryEmbedOperator(EmbeddingClient embeddingClient) {
        this.embeddingClient = embeddingClient;
    }

    @Override
    public OperatorDef definition() {
        return new OperatorDef(
                "query_embed", "query", "查询向量化",
                "调用嵌入服务把查询文本转成向量",
                List.of(SlotDecl.required("query", SlotType.STRING, "查询文本")),
                List.of(SlotDecl.required("queryEmbedding", SlotType.VECTOR, "查询向量")),
                PARAM_SCHEMA,
                ErrorPolicy.FAIL_FAST);
    }

    @Override
    public SlotValues execute(SlotValues inputs, Params params, ExecContext ctx) {
        String query = inputs.getString("query");
        if (query == null || query.isBlank()) {
            throw new OperatorException("query_embed: empty query");
        }
        if (!embeddingClient.isConfigured()) {
            throw new OperatorException("query_embed: embedding service not configured (LLM_SERVICE_URL blank)");
        }
        float[] vec = embeddingClient.embed(query);
        if (vec == null || vec.length == 0) {
            throw new OperatorException("query_embed: embedding service returned no vector");
        }
        return SlotValues.of("queryEmbedding", vec);
    }
}
