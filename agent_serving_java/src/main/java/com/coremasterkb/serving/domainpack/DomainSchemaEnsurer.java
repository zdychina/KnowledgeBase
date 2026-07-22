package com.coremasterkb.serving.domainpack;

import javax.sql.DataSource;

/**
 * Hook invoked by {@link DomainPoolManager} once per resolved DataSource so
 * serving-owned tables can be created in whichever database a domain routes to.
 *
 * <p>Implementations must never throw — a schema failure degrades an optional
 * feature, it must not stop the domain's pool from serving reads.</p>
 */
@FunctionalInterface
public interface DomainSchemaEnsurer {

    /** No-op ensurer, used by tests and by the legacy two-arg constructor. */
    DomainSchemaEnsurer NOOP = (dataSource, domain) -> { };

    void ensure(DataSource dataSource, String domain);
}
