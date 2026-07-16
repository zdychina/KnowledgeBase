package com.coremasterkb.serving.operator.operators.query;

import com.coremasterkb.serving.application.MultiQueryExpander;
import com.coremasterkb.serving.operator.core.*;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * {@code multi_query} — expand the query into semantic variants (original first). Reuses the
 * existing {@link MultiQueryExpander}. The {@code maxVariants} param caps the number of extra
 * variants kept.
 *
 * <p>Note: the current operator set has no consumer for the {@code variants} STRING_LIST output —
 * fanning variants out into parallel retrieval is a future engine feature; this operator exists so
 * the catalog is complete and the expansion is available.</p>
 */
@Component
public class MultiQueryOperator implements Operator {

    private static final String PARAM_SCHEMA = """
            {"type":"object","properties":{
              "maxVariants":{"type":"integer","minimum":0,"maximum":10,"default":2,"title":"额外变体数"}
            }}""";

    private final MultiQueryExpander expander;

    public MultiQueryOperator(MultiQueryExpander expander) {
        this.expander = expander;
    }

    @Override
    public OperatorDef definition() {
        return new OperatorDef(
                "multi_query", "query", "多查询扩展",
                "把查询扩展为多个语义变体（原始查询在首位）",
                List.of(SlotDecl.required("query", SlotType.STRING, "查询文本")),
                List.of(SlotDecl.required("variants", SlotType.STRING_LIST, "查询变体(含原始)")),
                PARAM_SCHEMA,
                ErrorPolicy.FAIL_FAST);
    }

    @Override
    public SlotValues execute(SlotValues inputs, Params params, ExecContext ctx) {
        String query = inputs.getString("query");
        int maxVariants = params.getInt("maxVariants", 2);
        List<String> all = expander.expand(query);
        // expander returns [original, variant1, variant2...]; cap extras at maxVariants
        int keep = Math.min(all.size(), 1 + Math.max(0, maxVariants));
        return SlotValues.of("variants", List.copyOf(all.subList(0, keep)));
    }
}
