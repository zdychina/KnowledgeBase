package com.coremasterkb.serving.operator.operators.query;

import com.coremasterkb.serving.infrastructure.EmbeddingClient;
import com.coremasterkb.serving.operator.core.*;
import com.coremasterkb.serving.operator.core.exceptions.OperatorException;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * {@code hyde} — Hypothetical Document Embeddings: ask the LLM to draft a hypothetical answer,
 * then embed that instead of the bare query. Reuses {@link EmbeddingClient#embedHyDE(String)}
 * (which already falls back to plain query embedding on failure). Output type matches
 * {@code query_embed} so the two are interchangeable upstream of {@code dense_vector}.
 */
@Component
public class HydeOperator implements Operator {

    private static final String PARAM_SCHEMA = "{\"type\":\"object\",\"properties\":{}}";

    private final EmbeddingClient embeddingClient;

    public HydeOperator(EmbeddingClient embeddingClient) {
        this.embeddingClient = embeddingClient;
    }

    @Override
    public OperatorDef definition() {
        return new OperatorDef(
                "hyde", "query", "HyDE",
                "先用 LLM 生成假设性文档再嵌入，提升语义召回",
                List.of(SlotDecl.required("query", SlotType.STRING, "查询文本")),
                List.of(SlotDecl.required("queryEmbedding", SlotType.VECTOR, "假设文档向量")),
                PARAM_SCHEMA,
                ErrorPolicy.FAIL_FAST);
    }

    @Override
    public SlotValues execute(SlotValues inputs, Params params, ExecContext ctx) {
        String query = inputs.getString("query");
        if (query == null || query.isBlank()) {
            throw new OperatorException("hyde: empty query");
        }
        if (!embeddingClient.isConfigured()) {
            throw new OperatorException("hyde: embedding service not configured");
        }
        float[] vec = embeddingClient.embedHyDE(query);
        if (vec == null || vec.length == 0) {
            throw new OperatorException("hyde: produced no vector");
        }
        return SlotValues.of("queryEmbedding", vec);
    }
}
