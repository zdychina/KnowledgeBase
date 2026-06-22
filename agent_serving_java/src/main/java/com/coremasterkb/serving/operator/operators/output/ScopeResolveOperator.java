package com.coremasterkb.serving.operator.operators.output;

import com.coremasterkb.serving.domain.ActiveScope;
import com.coremasterkb.serving.operator.core.*;
import com.coremasterkb.serving.repository.AssetRepository;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * {@code scope_resolve} — resolve the active release/build/snapshots for the request's
 * domain + channel. Reuses {@link AssetRepository#resolveActiveScope(String, String)} (read-only).
 * Stashes {@code releaseId}/{@code buildId} into {@link ExecContext} attributes for downstream use.
 */
@Component
public class ScopeResolveOperator implements Operator {

    private static final String PARAM_SCHEMA = "{\"type\":\"object\",\"properties\":{}}";

    private final AssetRepository assetRepository;

    public ScopeResolveOperator(AssetRepository assetRepository) {
        this.assetRepository = assetRepository;
    }

    @Override
    public OperatorDef definition() {
        return new OperatorDef(
                "scope_resolve", "scope", "范围解析",
                "根据 domain/channel 解析当前生效的 release 与文档快照范围",
                List.of(),
                List.of(SlotDecl.required("scope", SlotType.SCOPE, "检索范围(snapshotIds)")),
                PARAM_SCHEMA,
                ErrorPolicy.FAIL_FAST);
    }

    @Override
    public SlotValues execute(SlotValues inputs, Params params, ExecContext ctx) {
        ActiveScope scope = assetRepository.resolveActiveScope(ctx.domain(), ctx.channel());
        ctx.putAttribute("releaseId", scope.releaseId());
        ctx.putAttribute("buildId", scope.buildId());
        ctx.putAttribute("snapshotCount", scope.snapshotIds().size());
        return SlotValues.of("scope", scope);
    }
}
