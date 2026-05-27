package com.coremasterkb.serving.domainpack;

import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

import javax.sql.DataSource;
import java.sql.Connection;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Manages per-domain DataSource instances.
 *
 * <p>When a domain's {@code database_url_env} resolves to a JDBC URL that differs
 * from the default connection, a dedicated HikariCP pool is created for that domain.
 * When the env var is absent the default DataSource is reused transparently.
 *
 * <p>Pools are created lazily on first access and cached for the lifetime of the
 * application. The registry is consulted once at startup to warn about misconfigured
 * domains, but pool creation does not block startup.
 *
 * <p>Call {@link #getDataSource(String)} before any DB operation for a domain.
 * It throws {@code IllegalStateException("domain_database_unavailable")} when the
 * domain's configured database cannot be reached.
 */
@Component
public class DomainPoolManager {

    private static final Logger log = LoggerFactory.getLogger(DomainPoolManager.class);

    private final DomainRegistry domainRegistry;
    private final DataSource defaultDataSource;
    private final Environment environment;

    /** domain → resolved DataSource (may be the default for unconfigured domains). */
    private final Map<String, DataSource> pools = new ConcurrentHashMap<>();
    /** Tracks HikariDataSources we own so we can close them on shutdown. */
    private final List<HikariDataSource> ownedPools = new ArrayList<>();

    public DomainPoolManager(DomainRegistry domainRegistry,
                              @Qualifier("defaultDataSource") DataSource defaultDataSource,
                              Environment environment) {
        this.domainRegistry = domainRegistry;
        this.defaultDataSource = defaultDataSource;
        this.environment = environment;
    }

    @PostConstruct
    public void init() {
        if (!domainRegistry.isLoaded()) {
            log.info("Domain registry not loaded — DomainPoolManager running in single-datasource mode");
            return;
        }
        // Log registered domains without connecting — pools are created lazily on first request
        // to avoid blocking startup when many domain databases exist.
        for (String domain : domainRegistry.knownDomains()) {
            log.info("Domain registered: {} (pool will be created on first request)", domain);
        }
    }

    /**
     * Returns the DataSource to use for the given domain.
     *
     * @throws IllegalStateException("domain_database_unavailable") if the domain's configured DB
     *         is unreachable
     */
    public DataSource getDataSource(String domain) {
        return pools.computeIfAbsent(domain, this::resolveDataSource);
    }

    private DataSource resolveDataSource(String domain) {
        return domainRegistry.findEntry(domain)
                .filter(e -> e.databaseUrlEnv() != null && !e.databaseUrlEnv().isBlank())
                .map(entry -> {
                    String jdbcUrl = environment.getProperty(entry.databaseUrlEnv());
                    if (jdbcUrl == null || jdbcUrl.isBlank()) {
                        log.debug("Env var '{}' not set for domain '{}' — using default DataSource",
                                entry.databaseUrlEnv(), domain);
                        return defaultDataSource;
                    }
                    log.info("Creating dedicated pool for domain '{}' from env var '{}'",
                            domain, entry.databaseUrlEnv());
                    return createHikariPool(domain, jdbcUrl);
                })
                .orElse(defaultDataSource);
    }

    private DataSource createHikariPool(String domain, String jdbcUrl) {
        HikariConfig cfg = new HikariConfig();
        cfg.setJdbcUrl(jdbcUrl);
        cfg.setPoolName("hikari-" + domain);
        cfg.setMinimumIdle(2);
        cfg.setMaximumPoolSize(10);
        cfg.setConnectionTimeout(5_000);
        cfg.setInitializationFailTimeout(5_000);
        try {
            HikariDataSource ds = new HikariDataSource(cfg);
            // Eagerly verify the connection
            try (Connection conn = ds.getConnection()) {
                if (!conn.isValid(3)) {
                    ds.close();
                    throw new IllegalStateException("domain_database_unavailable");
                }
            }
            synchronized (ownedPools) {
                ownedPools.add(ds);
            }
            return ds;
        } catch (IllegalStateException e) {
            throw e;
        } catch (Exception e) {
            log.error("Cannot connect to domain '{}' database: {}", domain, e.getMessage());
            throw new IllegalStateException("domain_database_unavailable");
        }
    }

    @PreDestroy
    public void shutdown() {
        synchronized (ownedPools) {
            for (HikariDataSource ds : ownedPools) {
                try {
                    ds.close();
                    log.info("Closed pool: {}", ds.getPoolName());
                } catch (Exception e) {
                    log.warn("Error closing pool {}: {}", ds.getPoolName(), e.getMessage());
                }
            }
            ownedPools.clear();
        }
    }
}
