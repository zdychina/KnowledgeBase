package com.coremasterkb.serving.domain;

import java.util.List;
import java.util.Map;

/**
 * Complete retrieval plan: routes to execute, filters, fusion, rerank, assembly, and expansion config.
 *
 * @param routes    route configurations; defaults to empty list
 * @param filters   retrieval filters; defaults to empty map
 * @param fusion    fusion configuration; defaults to new FusionConfig(null, 60)
 * @param rerank    rerank configuration; defaults to new RerankConfig(null, null)
 * @param assembly  assembly configuration; defaults to AssemblyConfig.defaults()
 * @param expansion expansion configuration; defaults to ExpansionConfig.defaults()
 */
public record RetrievalRoutePlan(
        List<RouteConfig> routes,
        Map<String, Object> filters,
        FusionConfig fusion,
        RerankConfig rerank,
        AssemblyConfig assembly,
        ExpansionConfig expansion
) {
    public RetrievalRoutePlan {
        if (routes == null) routes = List.of();
        if (filters == null) filters = Map.of();
        if (fusion == null) fusion = new FusionConfig(null, 60);
        if (rerank == null) rerank = new RerankConfig(null, null);
        if (assembly == null) assembly = AssemblyConfig.defaults();
        if (expansion == null) expansion = ExpansionConfig.defaults();
    }
}
