package com.coremasterkb.serving.domainpack;

import java.util.Map;

/**
 * An immutable point-in-time view of all per-domain config Serving consumes,
 * as fetched from main_control's {@code GET /api/v1/serving-config} (or built from
 * the local-file fallback). Fed atomically into {@link DomainRegistry},
 * {@link DomainPackReader} and {@link DomainPoolManager} on startup and on reload.
 */
public record ServingConfigSnapshot(Map<String, DomainConfig> domains) {

    public ServingConfigSnapshot {
        if (domains == null) domains = Map.of();
    }

    /**
     * One domain's slice of the snapshot.
     *
     * @param domainId       domain identifier
     * @param enabled        whether the domain accepts traffic
     * @param defaultChannel release channel when the caller omits one
     * @param database       inline DB connection, or {@code null} → use default DataSource
     * @param serving        the scenario pack's {@code serving:} block (route_policy,
     *                       query_understanding, extractor_rules, intent_strategy)
     */
    public record DomainConfig(
            String domainId,
            boolean enabled,
            String defaultChannel,
            DatabaseConfig database,
            Map<String, Object> serving
    ) {
        public DomainConfig {
            if (defaultChannel == null || defaultChannel.isBlank()) defaultChannel = "prod";
            if (serving == null) serving = Map.of();
        }
    }
}
