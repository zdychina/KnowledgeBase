package com.coremasterkb.serving.domainpack;

/**
 * A single domain's registry config, sourced from main_control's serving-config snapshot.
 *
 * @param domain          domain identifier (e.g. "cloud_core_network")
 * @param enabled         whether this domain accepts traffic; false → 400 domain_disabled
 * @param database        inline DB connection, or {@code null} → reuse the default DataSource
 * @param defaultChannel  release channel used when the caller omits channel (default: "prod")
 */
public record DomainRegistryEntry(
        String domain,
        boolean enabled,
        DatabaseConfig database,
        String defaultChannel
) {
    public DomainRegistryEntry {
        if (defaultChannel == null || defaultChannel.isBlank()) defaultChannel = "prod";
    }
}
