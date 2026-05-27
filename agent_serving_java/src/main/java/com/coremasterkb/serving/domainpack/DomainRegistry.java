package com.coremasterkb.serving.domainpack;

import com.coremasterkb.serving.config.ServingProperties;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.yaml.snakeyaml.Yaml;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Loads domain_registry.yaml at startup and provides domain validation and config lookup.
 *
 * <p>When the registry file is present:
 * <ul>
 *   <li>Unknown domains throw {@code IllegalArgumentException("unknown_domain")}.</li>
 *   <li>Disabled domains throw {@code IllegalArgumentException("domain_disabled")}.</li>
 * </ul>
 * When the registry file is absent (dev/test), all lookups return null and no enforcement applies.
 */
@Component
public class DomainRegistry {

    private static final Logger log = LoggerFactory.getLogger(DomainRegistry.class);

    private final Map<String, DomainRegistryEntry> entries = new ConcurrentHashMap<>();
    private final String registryPath;

    public DomainRegistry(ServingProperties props) {
        this.registryPath = props.domainRegistryPath();
    }

    @PostConstruct
    public void init() {
        Path path = Paths.get(registryPath);
        if (!Files.exists(path)) {
            log.info("Domain registry not found at '{}' — running without registry enforcement", registryPath);
            return;
        }
        try {
            load(path);
            log.info("Loaded domain registry: {} domain(s) — {}", entries.size(), entries.keySet());
        } catch (Exception e) {
            log.warn("Failed to load domain registry '{}': {}", registryPath, e.getMessage());
        }
    }

    @SuppressWarnings("unchecked")
    private void load(Path path) throws IOException {
        Yaml yaml = new Yaml();
        try (InputStream is = Files.newInputStream(path)) {
            Map<String, Object> root = yaml.load(is);
            Map<String, Object> domains = (Map<String, Object>) root.getOrDefault("domains", Map.of());
            for (var kv : domains.entrySet()) {
                String domainId = kv.getKey();
                Map<String, Object> cfg = (Map<String, Object>) kv.getValue();
                DomainRegistryEntry entry = new DomainRegistryEntry(
                        domainId,
                        Boolean.TRUE.equals(cfg.get("enabled")),
                        (String) cfg.get("database_url_env"),
                        (String) cfg.getOrDefault("scenario_pack", domainId),
                        (String) cfg.getOrDefault("default_channel", "prod")
                );
                entries.put(domainId, entry);
                log.debug("Registered domain: {} enabled={} channel={}", domainId, entry.enabled(), entry.defaultChannel());
            }
        }
    }

    /**
     * Validate and return the registry entry for the given domain.
     *
     * @return entry, or {@code null} if the registry was not loaded (no enforcement)
     * @throws IllegalArgumentException("unknown_domain")  if registry is loaded and domain is not listed
     * @throws IllegalArgumentException("domain_disabled") if the domain is disabled
     */
    public DomainRegistryEntry resolve(String domain) {
        if (entries.isEmpty()) return null;
        DomainRegistryEntry entry = entries.get(domain);
        if (entry == null) {
            log.warn("Unknown domain '{}', known domains: {}", domain, entries.keySet());
            throw new IllegalArgumentException("unknown_domain");
        }
        if (!entry.enabled()) {
            log.warn("Disabled domain '{}'", domain);
            throw new IllegalArgumentException("domain_disabled");
        }
        return entry;
    }

    /**
     * Return the default channel for the domain, or {@code "prod"} if not configured.
     * Never throws — safe to call after domain has already been validated.
     */
    public String getDefaultChannel(String domain) {
        DomainRegistryEntry entry = entries.get(domain);
        return (entry != null) ? entry.defaultChannel() : "prod";
    }

    /**
     * Silent lookup — returns empty if registry not loaded or domain not found.
     * Never throws. Use this for informational/debug reads after validation has already passed.
     */
    public Optional<DomainRegistryEntry> findEntry(String domain) {
        return Optional.ofNullable(entries.get(domain));
    }

    public boolean isLoaded() {
        return !entries.isEmpty();
    }

    public Set<String> knownDomains() {
        return Collections.unmodifiableSet(entries.keySet());
    }
}
