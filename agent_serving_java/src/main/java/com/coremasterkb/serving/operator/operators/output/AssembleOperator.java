package com.coremasterkb.serving.operator.operators.output;

import com.coremasterkb.serving.application.ContextAssembler;
import com.coremasterkb.serving.domain.ActiveScope;
import com.coremasterkb.serving.domain.AssemblyConfig;
import com.coremasterkb.serving.domain.ContextPack;
import com.coremasterkb.serving.domain.QueryUnderstanding;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.RetrievalRoutePlan;
import com.coremasterkb.serving.operator.core.*;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

/**
 * {@code assemble} — terminal output operator for production paradigms. Reuses the existing
 * {@link ContextAssembler} to turn candidates into a {@link ContextPack} (seed items → source
 * drill-down → graph expansion → evidence roles → compression), the same structure the existing
 * {@code /api/v1/search} returns.
 */
@Component
public class AssembleOperator implements Operator {

    private static final String PARAM_SCHEMA = """
            {"type":"object","properties":{
              "maxItems":{"type":"integer","minimum":1,"maximum":50,"default":10,"title":"最大条目数"},
              "maxExpanded":{"type":"integer","minimum":0,"maximum":50,"default":20,"title":"最大扩展数"},
              "relationExpansion":{"type":"boolean","default":true,"title":"启用关系扩展"}
            }}""";

    private final ContextAssembler assembler;

    public AssembleOperator(ContextAssembler assembler) {
        this.assembler = assembler;
    }

    @Override
    public OperatorDef definition() {
        return new OperatorDef(
                "assemble", "output", "组装上下文（生产用）",
                "终点算子：把候选组装为 ContextPack（含图扩展/证据分组/压缩）",
                List.of(
                        SlotDecl.required("candidates", SlotType.CANDIDATE_LIST, "候选"),
                        SlotDecl.required("understanding", SlotType.QUERY_UNDERSTANDING, "查询理解"),
                        SlotDecl.required("scope", SlotType.SCOPE, "检索范围")),
                List.of(SlotDecl.required("contextPack", SlotType.CONTEXT_PACK, "上下文包(终点)")),
                PARAM_SCHEMA,
                ErrorPolicy.FAIL_FAST);
    }

    @Override
    public SlotValues execute(SlotValues inputs, Params params, ExecContext ctx) {
        List<RetrievalCandidate> candidates = inputs.getCandidates("candidates");
        QueryUnderstanding understanding = inputs.getUnderstanding("understanding");
        ActiveScope scope = inputs.getScope("scope");

        int maxItems = params.getInt("maxItems", 10);
        int maxExpanded = params.getInt("maxExpanded", 20);
        boolean relationExpansion = params.getBool("relationExpansion", true);

        AssemblyConfig assembly = new AssemblyConfig(
                true, relationExpansion, maxItems, maxExpanded, 2,
                AssemblyConfig.defaults().relationTypes());
        RetrievalRoutePlan routePlan = new RetrievalRoutePlan(
                List.of(), Map.of(), null, null, assembly, null);

        String query = understanding != null ? understanding.originalQuery() : "";
        ContextPack pack = assembler.assemble(query, understanding, scope, candidates, routePlan);
        return SlotValues.of("contextPack", pack);
    }
}
