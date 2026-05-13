package com.coremasterkb.serving.domainpack;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.springframework.core.env.Environment;

import javax.sql.DataSource;
import java.util.Optional;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

@DisplayName("DomainPoolManager")
class DomainPoolManagerTest {

    private final DomainRegistry registry = mock(DomainRegistry.class);
    private final DataSource defaultDs = mock(DataSource.class);
    private final Environment env = mock(Environment.class);

    @Nested
    @DisplayName("no registry loaded")
    class NoRegistry {
        @Test
        @DisplayName("getDataSource returns default DataSource when registry not loaded")
        void returnsDefaultWhenRegistryEmpty() {
            when(registry.isLoaded()).thenReturn(false);
            when(registry.knownDomains()).thenReturn(Set.of());
            when(registry.findEntry(anyString())).thenReturn(Optional.empty());

            DomainPoolManager mgr = new DomainPoolManager(registry, defaultDs, env);
            mgr.init();

            DataSource result = mgr.getDataSource("cloud_core_network");
            assertThat(result).isSameAs(defaultDs);
        }
    }

    @Nested
    @DisplayName("registry loaded, no env var set")
    class RegistryLoadedNoEnvVar {
        @Test
        @DisplayName("getDataSource returns default when databaseUrlEnv is null")
        void returnsDefaultWhenEnvVarNull() {
            when(registry.isLoaded()).thenReturn(true);
            when(registry.knownDomains()).thenReturn(Set.of("cloud_core_network"));
            var entry = new DomainRegistryEntry("cloud_core_network", true, null, "cloud_core_network", "prod");
            when(registry.findEntry("cloud_core_network")).thenReturn(Optional.of(entry));

            DomainPoolManager mgr = new DomainPoolManager(registry, defaultDs, env);
            mgr.init();

            DataSource result = mgr.getDataSource("cloud_core_network");
            assertThat(result).isSameAs(defaultDs);
        }

        @Test
        @DisplayName("getDataSource returns default when env var not set in environment")
        void returnsDefaultWhenEnvVarNotSet() {
            when(registry.isLoaded()).thenReturn(true);
            when(registry.knownDomains()).thenReturn(Set.of("cloud_core_network"));
            // env mock returns null for any unstubbed property — simulates missing var
            var entry = new DomainRegistryEntry("cloud_core_network", true,
                    "COREMASTERKB_TEST_UNSET_ENV_VAR_12345", "cloud_core_network", "prod");
            when(registry.findEntry("cloud_core_network")).thenReturn(Optional.of(entry));

            DomainPoolManager mgr = new DomainPoolManager(registry, defaultDs, env);
            mgr.init();

            DataSource result = mgr.getDataSource("cloud_core_network");
            assertThat(result).isSameAs(defaultDs);
        }
    }

    @Nested
    @DisplayName("domain not in registry")
    class UnknownDomain {
        @Test
        @DisplayName("getDataSource returns default for unregistered domain")
        void returnsDefaultForUnknownDomain() {
            when(registry.isLoaded()).thenReturn(true);
            when(registry.knownDomains()).thenReturn(Set.of());
            when(registry.findEntry(anyString())).thenReturn(Optional.empty());

            DomainPoolManager mgr = new DomainPoolManager(registry, defaultDs, env);
            mgr.init();

            DataSource result = mgr.getDataSource("nonexistent");
            assertThat(result).isSameAs(defaultDs);
        }
    }
}
