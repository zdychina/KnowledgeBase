package com.coremasterkb.serving.domainpack;

import java.util.Objects;

/**
 * A domain's database connection, sourced from main_control's inline {@code database}
 * block. For the local-file fallback path the connection may be supplied pre-built via
 * {@link #jdbcUrl}.
 *
 * <p>All fields are nullable; {@link #isUsable()} reports whether enough is present to
 * build a dedicated pool. When not usable the caller falls back to the default DataSource.</p>
 */
public record DatabaseConfig(
        String jdbcUrl,     // pre-built URL (file-fallback / env path); when set it wins
        String host,
        Integer port,
        String dbname,
        String user,
        String password,
        String sslmode,
        String gssencmode,
        Integer poolMin,
        Integer poolMax
) {
    /** True when a dedicated pool can be built (either a raw URL or host+dbname). */
    public boolean isUsable() {
        if (jdbcUrl != null && !jdbcUrl.isBlank()) return true;
        return host != null && !host.isBlank() && dbname != null && !dbname.isBlank();
    }

    /** Effective JDBC URL: the raw url when present, else assembled from host/port/dbname. */
    public String resolvedJdbcUrl() {
        if (jdbcUrl != null && !jdbcUrl.isBlank()) return jdbcUrl;
        int p = port != null ? port : 5432;
        StringBuilder sb = new StringBuilder("jdbc:postgresql://")
                .append(host).append(':').append(p).append('/').append(dbname);
        StringBuilder params = new StringBuilder();
        if (sslmode != null && !sslmode.isBlank()) params.append("sslmode=").append(sslmode);
        if (gssencmode != null && !gssencmode.isBlank()) {
            if (params.length() > 0) params.append('&');
            params.append("gssencmode=").append(gssencmode);
        }
        if (params.length() > 0) sb.append('?').append(params);
        return sb.toString();
    }

    /** Stable signature used to detect changes across reloads (drives pool rebuild). */
    public String signature() {
        return String.join("|",
                String.valueOf(jdbcUrl), String.valueOf(host), String.valueOf(port),
                String.valueOf(dbname), String.valueOf(user), String.valueOf(password),
                String.valueOf(sslmode), String.valueOf(gssencmode),
                String.valueOf(poolMin), String.valueOf(poolMax));
    }

    public static boolean sameSignature(DatabaseConfig a, DatabaseConfig b) {
        String sa = a != null ? a.signature() : null;
        String sb = b != null ? b.signature() : null;
        return Objects.equals(sa, sb);
    }
}
