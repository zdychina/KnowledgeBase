package com.coremasterkb.serving.domainpack;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import javax.sql.DataSource;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

@DisplayName("DomainPoolManager")
class DomainPoolManagerTest {

    private final DomainRegistry registry = mock(DomainRegistry.class);
    private final DataSource defaultDs = mock(DataSource.class);

    @Test
    @DisplayName("returns default DataSource for a domain not in the registry")
    void returnsDefaultForUnknownDomain() {
        when(registry.findEntry(anyString())).thenReturn(Optional.empty());

        DomainPoolManager mgr = new DomainPoolManager(registry, defaultDs);

        assertThat(mgr.getDataSource("nonexistent")).isSameAs(defaultDs);
    }

    @Test
    @DisplayName("returns default DataSource when entry has no inline database")
    void returnsDefaultWhenNoDatabase() {
        var entry = new DomainRegistryEntry("cloud_core_network", true, null, "prod");
        when(registry.findEntry("cloud_core_network")).thenReturn(Optional.of(entry));

        DomainPoolManager mgr = new DomainPoolManager(registry, defaultDs);

        assertThat(mgr.getDataSource("cloud_core_network")).isSameAs(defaultDs);
    }

    @Test
    @DisplayName("returns default DataSource when database config is not usable")
    void returnsDefaultWhenDbNotUsable() {
        var db = new DatabaseConfig(null, null, null, null, null, null, null, null, null, null);
        var entry = new DomainRegistryEntry("cloud_core_network", true, db, "prod");
        when(registry.findEntry("cloud_core_network")).thenReturn(Optional.of(entry));

        DomainPoolManager mgr = new DomainPoolManager(registry, defaultDs);

        assertThat(mgr.getDataSource("cloud_core_network")).isSameAs(defaultDs);
    }

    @Test
    @DisplayName("invalidate keeps the default mapping when nothing changed")
    void invalidateKeepsDefault() {
        when(registry.findEntry(anyString())).thenReturn(Optional.empty());
        DomainPoolManager mgr = new DomainPoolManager(registry, defaultDs);

        assertThat(mgr.getDataSource("d")).isSameAs(defaultDs);
        mgr.invalidate(); // no dedicated pools to close; default mapping unchanged
        assertThat(mgr.getDataSource("d")).isSameAs(defaultDs);
    }
}
