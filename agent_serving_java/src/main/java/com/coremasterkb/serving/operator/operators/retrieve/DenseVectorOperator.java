package com.coremasterkb.serving.operator.operators.retrieve;

import com.coremasterkb.serving.domain.ActiveScope;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.ScoreChain;
import com.coremasterkb.serving.mapper.result.EmbeddingRow;
import com.coremasterkb.serving.operator.core.*;
import com.coremasterkb.serving.operator.mapper.OperatorEmbeddingMapper;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * {@code dense_vector} — pgvector cosine retrieval with a {@code textKind} ("检索范围") parameter.
 *
 * <p>The defining new capability of the operator system: unlike the existing
 * {@code DenseVectorRetriever}, this filters embeddings by {@code text_kind} so raw_text / question /
 * both retrieve over different embedding sets. Uses {@link OperatorEmbeddingMapper} (new SQL).</p>
 */
@Component
public class DenseVectorOperator implements Operator {

    private static final String SOURCE = "dense_vector";

    private static final String PARAM_SCHEMA = """
            {"type":"object","properties":{
              "textKind":{"type":"string","enum":["raw_text","question","both"],"default":"raw_text","title":"检索范围"},
              "topK":{"type":"integer","minimum":1,"maximum":200,"default":20,"title":"返回数量"}
            }}""";

    private final OperatorEmbeddingMapper mapper;

    public DenseVectorOperator(OperatorEmbeddingMapper mapper) {
        this.mapper = mapper;
    }

    @Override
    public OperatorDef definition() {
        return new OperatorDef(
                "dense_vector", "retrieve", "向量检索",
                "pgvector 余弦相似度检索，可按 text_kind 限定检索范围",
                List.of(
                        SlotDecl.required("queryEmbedding", SlotType.VECTOR, "查询向量"),
                        SlotDecl.required("scope", SlotType.SCOPE, "检索范围(snapshotIds)")),
                List.of(SlotDecl.required("candidates", SlotType.CANDIDATE_LIST, "检索候选")),
                PARAM_SCHEMA,
                ErrorPolicy.SKIP_WITH_EMPTY);
    }

    @Override
    public SlotValues execute(SlotValues inputs, Params params, ExecContext ctx) {
        float[] vec = inputs.getVector("queryEmbedding");
        ActiveScope scope = inputs.getScope("scope");
        if (vec == null || vec.length == 0 || scope == null || scope.snapshotIds().isEmpty()) {
            return SlotValues.of("candidates", List.of());
        }

        List<String> textKinds = resolveTextKinds(params.getString("textKind", "raw_text"));
        int topK = params.getInt("topK", 20);

        List<EmbeddingRow> rows = mapper.selectTopKByVectorAndTextKind(
                scope.snapshotIds(), formatVector(vec), vec.length, textKinds, List.of(), topK);

        List<RetrievalCandidate> candidates = new ArrayList<>(rows.size());
        for (EmbeddingRow row : rows) {
            candidates.add(toCandidate(row));
        }
        return SlotValues.of("candidates", candidates);
    }

    /**
     * Map the "检索范围" param to concrete {@code asset_retrieval_units.unit_type} values
     * (both = raw_text + generated_question). The asset data stores the question carrier as
     * {@code generated_question}; embedding {@code text_kind} is uniformly 'full', so the range
     * filter targets the unit's {@code unit_type} (see OperatorEmbeddingMapper.xml).
     */
    private static List<String> resolveTextKinds(String textKind) {
        return switch (textKind) {
            case "question" -> List.of("generated_question");
            case "both" -> List.of("raw_text", "generated_question");
            default -> List.of("raw_text");
        };
    }

    private static String formatVector(float[] vec) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < vec.length; i++) {
            if (i > 0) sb.append(',');
            sb.append(vec[i]);
        }
        return sb.append(']').toString();
    }

    private static RetrievalCandidate toCandidate(EmbeddingRow row) {
        double score = row.getCosineScore();
        Map<String, Object> meta = new LinkedHashMap<>();
        putIfNotNull(meta, "document_snapshot_id", row.getDocumentSnapshotId());
        putIfNotNull(meta, "text", row.getText());
        putIfNotNull(meta, "title", row.getTitle());
        putIfNotNull(meta, "block_type", row.getBlockType());
        putIfNotNull(meta, "semantic_role", row.getSemanticRole());
        putIfNotNull(meta, "source_refs_json", row.getSourceRefsJson());
        putIfNotNull(meta, "facets_json", row.getFacetsJson());
        putIfNotNull(meta, "target_type", row.getTargetType());
        putIfNotNull(meta, "target_ref_json", row.getTargetRefJson());
        putIfNotNull(meta, "unit_type", row.getUnitType());
        putIfNotNull(meta, "source_segment_id", row.getSourceSegmentId());
        return new RetrievalCandidate(
                row.getRetrievalUnitId(), score, SOURCE, meta,
                new ScoreChain(score, 0.0, 0.0, List.of(SOURCE)));
    }

    private static void putIfNotNull(Map<String, Object> map, String key, Object val) {
        if (val != null) map.put(key, val);
    }
}
