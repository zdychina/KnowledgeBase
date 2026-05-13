package com.coremasterkb.serving.domainpack;

import org.springframework.jdbc.datasource.lookup.AbstractRoutingDataSource;
import org.springframework.lang.NonNull;
import org.springframework.lang.Nullable;

import javax.sql.DataSource;

/**
 * Routes every JDBC connection to the DataSource that owns the current request's domain.
 *
 * <p>The active domain is read from {@link DomainContext}. When no domain is set
 * (e.g. health-check threads, startup probes) the default DataSource is used.
 *
 * <p>Overrides {@code determineTargetDataSource()} completely so that domain-specific
 * pools created lazily by {@link DomainPoolManager} are always picked up without
 * needing to pre-populate the static target map.
 */
public class DomainRoutingDataSource extends AbstractRoutingDataSource {

    private final DomainPoolManager poolManager;
    private final DataSource defaultDataSource;

    public DomainRoutingDataSource(DomainPoolManager poolManager, DataSource defaultDataSource) {
        this.poolManager = poolManager;
        this.defaultDataSource = defaultDataSource;
        setDefaultTargetDataSource(defaultDataSource);
        setTargetDataSources(java.util.Map.of()); // required non-null by AbstractRoutingDataSource
    }

    /** Required by contract; not called because {@link #determineTargetDataSource()} is fully overridden. */
    @Nullable
    @Override
    protected Object determineCurrentLookupKey() {
        return DomainContext.get();
    }

    @NonNull
    @Override
    protected DataSource determineTargetDataSource() {
        String domain = DomainContext.get();
        if (domain == null) {
            return defaultDataSource;
        }
        // Returns domain-specific pool or falls back to default; throws domain_database_unavailable if misconfigured
        return poolManager.getDataSource(domain);
    }
}
