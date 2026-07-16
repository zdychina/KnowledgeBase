package com.coremasterkb.serving.operator.paradigm;

import com.zaxxer.hikari.HikariDataSource;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.stereotype.Component;

import javax.sql.DataSource;
import java.sql.Connection;

/**
 * Applies the paradigm DDL ({@code db/operator/001_operator_paradigm.sql}) against the
 * non-routed {@code defaultDataSource} on startup. Idempotent (CREATE TABLE IF NOT EXISTS) and
 * best-effort: a connection failure (e.g. the control DB not yet reachable) is logged, not fatal —
 * paradigm endpoints will then surface a clear error on first use.
 */
@Component
public class ParadigmSchemaInitializer {

    private static final Logger log = LoggerFactory.getLogger(ParadigmSchemaInitializer.class);

    private final DataSource defaultDataSource;

    public ParadigmSchemaInitializer(@Qualifier("defaultDataSource") HikariDataSource defaultDataSource) {
        this.defaultDataSource = defaultDataSource;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void initSchema() {
        ResourceDatabasePopulator populator = new ResourceDatabasePopulator();
        populator.addScript(new ClassPathResource("db/operator/001_operator_paradigm.sql"));
        populator.setContinueOnError(false);
        try (Connection conn = defaultDataSource.getConnection()) {
            populator.populate(conn);
            log.info("Operator paradigm schema ensured (operator_paradigm, operator_paradigm_version)");
        } catch (Exception e) {
            log.warn("Operator paradigm schema init skipped — control DB unavailable? ({}). "
                    + "Paradigm persistence endpoints will fail until the schema exists.", e.getMessage());
        }
    }
}
