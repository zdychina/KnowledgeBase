package com.coremasterkb.serving.domainpack;

import com.coremasterkb.serving.config.ServingProperties;
import com.coremasterkb.serving.domainpack.ServingConfigSnapshot.DomainConfig;
import com.coremasterkb.serving.infrastructure.MainControlClient;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Service;
import org.yaml.snakeyaml.Yaml;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Orchestrates loading the serving config and feeding it to the registry, pack reader and
 * pool manager — at startup and on every hot-reload. Fetches once from main_control; on
 * failure falls back to the local config files (keeps IntelliJ/dev and tests working when
 * main_control is not running).
 */
@Service
public class ConfigReloadService {

    private static final Logger log = LoggerFactory.getLogger(ConfigReloadService.class);

    private final MainControlClient mainControlClient;
    private final DomainRegistry domainRegistry;
    private final DomainPackReader domainPackReader;
    private final DomainPoolManager domainPoolManager;
    private final ServingProperties properties;
    private final Environment environment;

    public ConfigReloadService(MainControlClient mainControlClient,
                               DomainRegistry domainRegistry,
                               DomainPackReader domainPackReader,
                               DomainPoolManager domainPoolManager,
                               ServingProperties properties,
                               Environment environment) {
        this.mainControlClient = mainControlClient;
        this.domainRegistry = domainRegistry;
        this.domainPackReader = domainPackReader;
        this.domainPoolManager = domainPoolManager;
        this.properties = properties;
        this.environment = environment;
    }

    @PostConstruct
    public void init() {
        try {
            reload();
        } catch (Exception e) {
            // Never fail startup on config load — run lenient, recover via reload endpoint.
            log.warn("Initial config load failed, starting with lenient/empty config: {}", e.getMessage());
        }
    }

    /**
     * Fetch the snapshot (main_control first, local files as fallback) and apply it to all
     * three config holders. Order matters: registry first (pool manager reads it), then packs,
     * then invalidate stale pools.
     *
     * @return the number of domains applied
     */
    public synchronized int reload() {
        ServingConfigSnapshot snapshot;
        String source;
        try {
            snapshot = mainControlClient.fetchServingConfig();
            source = "main_control";
        } catch (Exception e) {
            log.warn("main_control fetch failed ({}), falling back to local files", e.getMessage());
            snapshot = loadFromFiles();
            source = "local_files";
        }
        domainRegistry.apply(snapshot);
        domainPackReader.apply(snapshot);
        domainPoolManager.invalidate();
        log.info("Config reload complete from {}: {} domain(s)", source, snapshot.domains().size());
        return snapshot.domains().size();
    }

    // -------------------------------------------------------------------------
    // Local-file fallback (legacy schema: domain_registry.yaml + scenario_packs/)
    // -------------------------------------------------------------------------

    @SuppressWarnings("unchecked")
    private ServingConfigSnapshot loadFromFiles() {
        Map<String, DomainConfig> domains = new LinkedHashMap<>();
        Path registryPath = Paths.get(properties.domainRegistryPath());
        if (!Files.exists(registryPath)) {
            log.info("No local registry at '{}' — empty config (lenient mode)", registryPath);
            return new ServingConfigSnapshot(domains);
        }
        try (InputStream is = Files.newInputStream(registryPath)) {
            Map<String, Object> root = new Yaml().load(is);
            Map<String, Object> registry = (Map<String, Object>) root.getOrDefault("domains", Map.of());
            for (var kv : registry.entrySet()) {
                String domainId = kv.getKey();
                if (!(kv.getValue() instanceof Map<?, ?> rawCfg)) continue;
                Map<String, Object> cfg = (Map<String, Object>) rawCfg;

                boolean enabled = Boolean.TRUE.equals(cfg.get("enabled"));
                String channel = cfg.get("default_channel") instanceof String s ? s : "prod";
                String packRef = cfg.get("scenario_pack") instanceof String p ? p : domainId;

                DatabaseConfig database = resolveLegacyDatabase(cfg.get("database_url_env"));
                Map<String, Object> serving = loadServingBlock(packRef);

                domains.put(domainId, new DomainConfig(domainId, enabled, channel, database, serving));
            }
        } catch (Exception e) {
            log.warn("Local-file fallback failed to parse registry '{}': {}", registryPath, e.getMessage());
        }
        return new ServingConfigSnapshot(domains);
    }

    /** Legacy path: database_url_env → env var → pre-built JDBC URL. */
    private DatabaseConfig resolveLegacyDatabase(Object envNameObj) {
        if (!(envNameObj instanceof String envName) || envName.isBlank()) return null;
        String jdbcUrl = environment.getProperty(envName);
        if (jdbcUrl == null || jdbcUrl.isBlank()) return null;
        return new DatabaseConfig(jdbcUrl, null, null, null, null, null, null, null, null, null);
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> loadServingBlock(String packRef) {
        Path yamlPath = Paths.get(properties.scenarioPacksDir()).resolve(packRef).resolve("domain.yaml");
        if (!Files.exists(yamlPath)) return Map.of();
        try (InputStream is = Files.newInputStream(yamlPath)) {
            Map<String, Object> data = new Yaml().load(is);
            Object serving = data != null ? data.get("serving") : null;
            return serving instanceof Map<?, ?> m ? (Map<String, Object>) m : Map.of();
        } catch (Exception e) {
            log.warn("Failed to read scenario pack '{}': {}", yamlPath, e.getMessage());
            return Map.of();
        }
    }
}
