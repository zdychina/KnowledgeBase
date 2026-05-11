package com.coremasterkb.serving.repository;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import javax.sql.DataSource;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.stream.Collectors;
import java.util.stream.Stream;

/**
 * Schema adapter: loads shared DDL for dev/test mode.
 * <p>
 * Reads the shared {@code databases/asset_core/schemas/001_asset_core.sqlite.sql}
 * and adapts it for the target database. This is the ONLY place where asset table
 * structure is loaded for dev/test mode.
 * <p>
 * Applies v1.2 migration: column {@code channel} renamed to {@code domain}
 * in {@code asset_publish_releases}, and corresponding index names updated.
 */
public class SchemaAdapter {

    private static final Logger log = LoggerFactory.getLogger(SchemaAdapter.class);

    private static final String SCHEMA_RESOURCE = "databases/asset_core/schemas/001_asset_core.sqlite.sql";

    /**
     * Load the shared SQLite DDL from the classpath or filesystem,
     * applying the channel-to-domain migration.
     *
     * @return adapted DDL script
     */
    public String loadDdl() {
        String raw = readSchemaFile();
        return applyDomainMigration(raw);
    }

    /**
     * Create all asset tables in the given DataSource using the adapted DDL.
     *
     * @param dataSource target database
     */
    public void createTables(DataSource dataSource) {
        String ddl = loadDdl();
        executeDdl(dataSource, ddl);
    }

    /**
     * Create all asset tables using a provided Connection.
     *
     * @param connection active database connection
     */
    public void createTables(Connection connection) {
        String ddl = loadDdl();
        executeDdl(connection, ddl);
    }

    // -------------------------------------------------------------------------
    // Internal helpers
    // -------------------------------------------------------------------------

    private String readSchemaFile() {
        // Try classpath first, then filesystem
        try {
            var resource = getClass().getClassLoader().getResourceAsStream(SCHEMA_RESOURCE);
            if (resource != null) {
                try (resource) {
                    return new String(resource.readAllBytes(), StandardCharsets.UTF_8);
                }
            }
        } catch (IOException e) {
            log.debug("Schema not found on classpath: {}", SCHEMA_RESOURCE);
        }

        // Fallback to filesystem relative path
        Path fsPath = Path.of(SCHEMA_RESOURCE);
        if (Files.exists(fsPath)) {
            try (Stream<String> lines = Files.lines(fsPath, StandardCharsets.UTF_8)) {
                return lines.collect(Collectors.joining("\n"));
            } catch (IOException e) {
                throw new IllegalStateException("Failed to read schema file: " + fsPath, e);
            }
        }

        throw new IllegalStateException("Schema file not found: " + SCHEMA_RESOURCE);
    }

    /**
     * Apply the v1.2 migration: rename {@code channel} to {@code domain}
     * in asset_publish_releases table and update index names.
     */
    private String applyDomainMigration(String ddl) {
        return ddl
                // Rename column in table definitions
                .replace("    channel              TEXT NOT NULL",
                         "    domain               TEXT NOT NULL")
                // Rename unique index
                .replace("uq_asset_publish_releases_channel_active",
                         "uq_asset_publish_releases_domain_active")
                // Rename regular index
                .replace("idx_asset_publish_releases_channel_status",
                         "idx_asset_publish_releases_domain_status")
                // Rename index column references
                .replace("ON asset_publish_releases(channel)",
                         "ON asset_publish_releases(domain)")
                .replace("ON asset_publish_releases(channel, status)",
                         "ON asset_publish_releases(domain, status)")
                // Update comments referencing channel
                .replace("one build to one channel",
                         "one build to one domain");
    }

    private void executeDdl(DataSource dataSource, String ddl) {
        try (Connection conn = dataSource.getConnection()) {
            executeDdl(conn, ddl);
        } catch (SQLException e) {
            throw new IllegalStateException("Failed to execute DDL", e);
        }
    }

    private void executeDdl(Connection connection, String ddl) {
        try {
            // SQLite supports executescript via Statement; for H2/PostgreSQL split on semicolons
            if (isSqlite(connection)) {
                try (Statement stmt = connection.createStatement()) {
                    stmt.executeUpdate("PRAGMA foreign_keys = ON");
                }
            }

            // Split DDL into individual statements and execute
            String[] statements = ddl.split(";");
            for (String sql : statements) {
                String trimmed = sql.trim();
                if (trimmed.isEmpty() || trimmed.startsWith("--")) {
                    continue;
                }
                // Skip PRAGMA for non-SQLite databases
                if (trimmed.startsWith("PRAGMA") && !isSqlite(connection)) {
                    continue;
                }
                // Skip SQLite-specific FTS and triggers for non-SQLite databases
                if (!isSqlite(connection)) {
                    if (trimmed.startsWith("CREATE VIRTUAL TABLE")
                        || trimmed.startsWith("CREATE TRIGGER")) {
                        continue;
                    }
                }
                try (Statement stmt = connection.createStatement()) {
                    stmt.executeUpdate(trimmed);
                }
            }
            connection.commit();
            log.info("Schema DDL executed successfully");
        } catch (SQLException e) {
            throw new IllegalStateException("Failed to execute DDL statements", e);
        }
    }

    private boolean isSqlite(Connection connection) throws SQLException {
        String url = connection.getMetaData().getURL();
        return url != null && url.contains("sqlite");
    }
}
