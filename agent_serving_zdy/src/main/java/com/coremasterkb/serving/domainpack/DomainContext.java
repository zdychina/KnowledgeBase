package com.coremasterkb.serving.domainpack;

/**
 * Thread-local carrier for the active domain during a search request.
 *
 * <p>Set by {@code SearchService} before any DB operation and cleared in a
 * finally block. {@code DomainRoutingDataSource} reads this value to pick the
 * correct connection pool for every JDBC call on the current thread.
 */
public final class DomainContext {

    private static final ThreadLocal<String> CURRENT = new ThreadLocal<>();

    private DomainContext() {}

    public static void set(String domain) {
        CURRENT.set(domain);
    }

    public static String get() {
        return CURRENT.get();
    }

    public static void clear() {
        CURRENT.remove();
    }
}
