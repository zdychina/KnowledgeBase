package com.coremasterkb.serving.domainpack;

/**
 * A single domain's configuration as read from domain_registry.yaml.
 *
 * @param domain          domain identifier (e.g. "cloud_core_network")
 * @param enabled         whether this domain accepts traffic; false → 400 domain_disabled
 * @param databaseUrlEnv  env var name that holds the PostgreSQL URL for this domain
 * @param scenarioPack    sub-directory name under scenario_packs/ for this domain
 * @param defaultChannel  release channel used when the caller omits channel (default: "prod")
 */
public record DomainRegistryEntry(
        String domain,
        boolean enabled,
        String databaseUrlEnv,
        String scenarioPack,
        String defaultChannel
) {
    public DomainRegistryEntry {
        if (defaultChannel == null || defaultChannel.isBlank()) defaultChannel = "prod";
        if (scenarioPack == null || scenarioPack.isBlank()) scenarioPack = domain;
    }
}
