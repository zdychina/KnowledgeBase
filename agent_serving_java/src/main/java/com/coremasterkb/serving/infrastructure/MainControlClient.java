package com.coremasterkb.serving.infrastructure;

import com.coremasterkb.serving.domainpack.DatabaseConfig;
import com.coremasterkb.serving.domainpack.ServingConfigSnapshot;
import com.coremasterkb.serving.domainpack.ServingConfigSnapshot.DomainConfig;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.RestTemplate;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Reads the per-domain serving config from main_control over HTTP
 * ({@code GET /api/v1/serving-config}). Serving does not read config files directly —
 * the local files are only a fallback, see {@code ConfigReloadService}.
 */
public class MainControlClient {

    private static final ParameterizedTypeReference<Map<String, Object>> MAP_TYPE =
            new ParameterizedTypeReference<>() {};

    private final RestTemplate restTemplate;
    private final String baseUrl;

    public MainControlClient(RestTemplate restTemplate, String baseUrl) {
        this.restTemplate = restTemplate;
        this.baseUrl = baseUrl != null ? baseUrl.replaceAll("/+$", "") : "";
    }

    public boolean isConfigured() {
        return baseUrl != null && !baseUrl.isBlank();
    }

    /**
     * Fetch and parse the serving-config snapshot.
     *
     * @throws ConfigFetchException on any transport / parse failure (caller decides fallback)
     */
    public ServingConfigSnapshot fetchServingConfig() {
        if (!isConfigured()) {
            throw new ConfigFetchException("main_control base-url not configured");
        }
        try {
            ResponseEntity<Map<String, Object>> response = restTemplate.exchange(
                    baseUrl + "/api/v1/serving-config",
                    HttpMethod.GET,
                    null,
                    MAP_TYPE);
            Map<String, Object> body = response.getBody();
            if (body == null) {
                throw new ConfigFetchException("empty body from main_control");
            }
            return parse(body);
        } catch (ConfigFetchException e) {
            throw e;
        } catch (Exception e) {
            throw new ConfigFetchException("fetch from main_control failed: " + e.getMessage(), e);
        }
    }

    @SuppressWarnings("unchecked")
    private ServingConfigSnapshot parse(Map<String, Object> body) {
        Map<String, Object> domains = body.get("domains") instanceof Map<?, ?> m
                ? (Map<String, Object>) m : Map.of();
        Map<String, DomainConfig> parsed = new LinkedHashMap<>();
        for (var entry : domains.entrySet()) {
            String domainId = entry.getKey();
            if (!(entry.getValue() instanceof Map<?, ?> raw)) continue;
            Map<String, Object> dc = (Map<String, Object>) raw;

            boolean enabled = !Boolean.FALSE.equals(dc.get("enabled"));
            String channel = dc.get("default_channel") instanceof String s ? s : "prod";
            DatabaseConfig database = parseDatabase(dc.get("database"));
            Map<String, Object> serving = dc.get("serving") instanceof Map<?, ?> sm
                    ? (Map<String, Object>) sm : Map.of();

            parsed.put(domainId, new DomainConfig(domainId, enabled, channel, database, serving));
        }
        return new ServingConfigSnapshot(parsed);
    }

    @SuppressWarnings("unchecked")
    private DatabaseConfig parseDatabase(Object obj) {
        if (!(obj instanceof Map<?, ?> raw)) return null;
        Map<String, Object> db = (Map<String, Object>) raw;
        return new DatabaseConfig(
                str(db.get("jdbc_url")),
                str(db.get("host")),
                intOrNull(db.get("port")),
                str(db.get("dbname")),
                str(db.get("user")),
                str(db.get("password")),
                str(db.get("sslmode")),
                str(db.get("gssencmode")),
                intOrNull(db.get("pool_min")),
                intOrNull(db.get("pool_max")));
    }

    private static String str(Object o) {
        return o != null ? String.valueOf(o) : null;
    }

    private static Integer intOrNull(Object o) {
        if (o instanceof Number n) return n.intValue();
        if (o instanceof String s && !s.isBlank()) {
            try {
                return Integer.parseInt(s.trim());
            } catch (NumberFormatException ignored) {
                return null;
            }
        }
        return null;
    }

    /** Thrown when the serving config cannot be fetched/parsed from main_control. */
    public static class ConfigFetchException extends RuntimeException {
        public ConfigFetchException(String message) {
            super(message);
        }

        public ConfigFetchException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
