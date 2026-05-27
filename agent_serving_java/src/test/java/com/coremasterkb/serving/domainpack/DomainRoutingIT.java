package com.coremasterkb.serving.domainpack;

import com.coremasterkb.serving.AgentServingApplication;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.core.env.Environment;
import org.springframework.test.context.ActiveProfiles;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

@SpringBootTest(classes = AgentServingApplication.class)
@ActiveProfiles("test-pg")
@Tag("pg-integration")
@DisplayName("DomainPoolManager IT — split-database routing")
class DomainRoutingIT {

    @Autowired
    private DomainPoolManager domainPoolManager;

    @Autowired
    @Qualifier("defaultDataSource")
    private DataSource defaultDataSource;

    @Autowired
    private Environment environment;

    @BeforeEach
    void skipIfDefaultDbUnreachable() {
        try (Connection conn = defaultDataSource.getConnection()) {
            assumeTrue(conn.isValid(3), "Default PostgreSQL not reachable — skipping");
        } catch (SQLException e) {
            assumeTrue(false, "Default PostgreSQL not reachable — skipping");
        }
    }

    // -------------------------------------------------------------------------
    // 1. Fallback: blank env var → reuse default DataSource
    // -------------------------------------------------------------------------

    @Test
    @DisplayName("blank COREMASTERKB_DB_CLOUD_CORE → falls back to default DataSource")
    void blankEnvVarFallsBackToDefault() {
        String url = environment.getProperty("COREMASTERKB_DB_CLOUD_CORE");
        assumeTrue(url == null || url.isBlank(),
                "COREMASTERKB_DB_CLOUD_CORE is set — this test is for the fallback case");

        DataSource ds = domainPoolManager.getDataSource("cloud_core_network");
        assertThat(ds).as("should reuse default datasource when env var is blank")
                .isSameAs(defaultDataSource);
    }

    // -------------------------------------------------------------------------
    // 2. Split DB: dedicated pool is created and reachable
    // -------------------------------------------------------------------------

    @Test
    @DisplayName("COREMASTERKB_DB_CLOUD_CORE set → dedicated pool, connection valid")
    void cloudCoreNetworkGetsDedicatedPool() throws SQLException {
        String url = environment.getProperty("COREMASTERKB_DB_CLOUD_CORE");
        assumeTrue(url != null && !url.isBlank(),
                "COREMASTERKB_DB_CLOUD_CORE not set — skipping dedicated-pool test");

        DataSource ds = domainPoolManager.getDataSource("cloud_core_network");
        assertThat(ds).as("dedicated pool must not be the default datasource")
                .isNotSameAs(defaultDataSource);

        try (Connection conn = ds.getConnection()) {
            assertThat(conn.isValid(3)).as("dedicated pool connection must be valid").isTrue();
        }
    }

    @Test
    @DisplayName("COREMASTERKB_DB_GENERIC set → dedicated pool, connection valid")
    void genericGetsDedicatedPool() throws SQLException {
        String url = environment.getProperty("COREMASTERKB_DB_GENERIC");
        assumeTrue(url != null && !url.isBlank(),
                "COREMASTERKB_DB_GENERIC not set — skipping dedicated-pool test");

        DataSource ds = domainPoolManager.getDataSource("generic");
        assertThat(ds).as("dedicated pool must not be the default datasource")
                .isNotSameAs(defaultDataSource);

        try (Connection conn = ds.getConnection()) {
            assertThat(conn.isValid(3)).as("dedicated pool connection must be valid").isTrue();
        }
    }

    // -------------------------------------------------------------------------
    // 3. Isolation: two domains point to physically different databases
    // -------------------------------------------------------------------------

    @Test
    @DisplayName("two domains with separate env vars → separate pools pointing to different DBs")
    void twoDomainsGetIsolatedPools() throws SQLException {
        String ccnUrl = environment.getProperty("COREMASTERKB_DB_CLOUD_CORE");
        String genUrl = environment.getProperty("COREMASTERKB_DB_GENERIC");
        assumeTrue(ccnUrl != null && !ccnUrl.isBlank(), "COREMASTERKB_DB_CLOUD_CORE not set");
        assumeTrue(genUrl != null && !genUrl.isBlank(), "COREMASTERKB_DB_GENERIC not set");

        DataSource ccnDs = domainPoolManager.getDataSource("cloud_core_network");
        DataSource genDs = domainPoolManager.getDataSource("generic");

        assertThat(ccnDs).isNotSameAs(defaultDataSource);
        assertThat(genDs).isNotSameAs(defaultDataSource);
        assertThat(ccnDs).isNotSameAs(genDs);

        String ccnDbName = currentDatabase(ccnDs);
        String genDbName = currentDatabase(genDs);
        String defaultDbName = currentDatabase(defaultDataSource);

        assertThat(ccnDbName).as("cloud_core_network DB must differ from default").isNotEqualTo(defaultDbName);
        assertThat(genDbName).as("generic DB must differ from default").isNotEqualTo(defaultDbName);
        assertThat(ccnDbName).as("cloud_core_network and generic must use different DBs").isNotEqualTo(genDbName);
    }

    // -------------------------------------------------------------------------
    // 4. Schema check: each domain DB must have the expected tables
    // -------------------------------------------------------------------------

    @Test
    @DisplayName("cloud_core_network dedicated DB has required tables")
    void cloudCoreNetworkDbHasSchema() throws SQLException {
        String url = environment.getProperty("COREMASTERKB_DB_CLOUD_CORE");
        assumeTrue(url != null && !url.isBlank(), "COREMASTERKB_DB_CLOUD_CORE not set");

        DataSource ds = domainPoolManager.getDataSource("cloud_core_network");
        assertThat(tableExists(ds, "asset_retrieval_units"))
                .as("asset_retrieval_units table must exist in cloud_core_network DB").isTrue();
        assertThat(tableExists(ds, "asset_publish_releases"))
                .as("asset_publish_releases table must exist in cloud_core_network DB").isTrue();
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    private static String currentDatabase(DataSource ds) throws SQLException {
        try (Connection conn = ds.getConnection();
             ResultSet rs = conn.createStatement().executeQuery("SELECT current_database()")) {
            return rs.next() ? rs.getString(1) : "";
        }
    }

    private static boolean tableExists(DataSource ds, String tableName) throws SQLException {
        try (Connection conn = ds.getConnection();
             ResultSet rs = conn.getMetaData().getTables(null, "public", tableName, new String[]{"TABLE"})) {
            return rs.next();
        }
    }
}
