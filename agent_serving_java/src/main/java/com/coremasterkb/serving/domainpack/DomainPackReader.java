package com.coremasterkb.serving.domainpack;

import com.coremasterkb.serving.config.ServingProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.*;

/**
 * Holds per-domain {@link ServingDomainProfile}s built from each domain's scenario-pack
 * {@code serving:} block (route_policy / query_understanding / extractor_rules /
 * intent_strategy). Sourced from main_control's serving-config snapshot and replaced
 * atomically on hot-reload via {@link #apply(ServingConfigSnapshot)}.
 *
 * <p>Note: this class no longer scans the packs directory itself. The old scan keyed
 * profiles by directory name, which was wrong whenever a domain's {@code scenario_pack}
 * differs from its domain id; the snapshot is keyed by domain id and resolves that
 * mapping on the main_control side.
 */
@Component
public class DomainPackReader {

    private static final Logger log = LoggerFactory.getLogger(DomainPackReader.class);

    /** Replaced wholesale on reload — volatile so readers see a consistent map. */
    private volatile Map<String, ServingDomainProfile> cache = Map.of();
    private final String defaultDomain;
    private final DomainRegistry domainRegistry;

    public DomainPackReader(ServingProperties props, DomainRegistry domainRegistry) {
        this.defaultDomain = props.defaultDomain();
        this.domainRegistry = domainRegistry;
    }

    /** Rebuild the profile cache from a snapshot, replacing the previous view atomically. */
    public void apply(ServingConfigSnapshot snapshot) {
        Map<String, ServingDomainProfile> next = new LinkedHashMap<>();
        for (var e : snapshot.domains().entrySet()) {
            try {
                next.put(e.getKey(), parseProfile(e.getKey(), e.getValue().serving()));
            } catch (Exception ex) {
                log.warn("Failed to build profile for domain {}: {}", e.getKey(), ex.getMessage());
            }
        }
        this.cache = Collections.unmodifiableMap(next);
        log.info("Domain packs applied: {} — {}", next.size(), next.keySet());
    }

    public ServingDomainProfile getProfile(String domainId) {
        String effectiveDomain = (domainId == null || domainId.isBlank()) ? defaultDomain : domainId;

        // Registry validation: throws unknown_domain / domain_disabled when registry is non-empty
        domainRegistry.resolve(effectiveDomain);

        ServingDomainProfile profile = cache.get(effectiveDomain);
        if (profile != null) {
            return profile;
        }

        // Registry empty (lenient mode) but some packs known → treat unknown domain as error
        if (!domainRegistry.isLoaded() && !cache.isEmpty()) {
            log.warn("Unknown domain '{}', known domains: {}", effectiveDomain, cache.keySet());
            throw new IllegalArgumentException("unknown_domain");
        }

        log.debug("No scenario pack for domain '{}', using defaults", effectiveDomain);
        return ServingDomainProfile.defaults(effectiveDomain);
    }

    /**
     * Build a profile from a scenario pack's {@code serving:} block. The block is the root
     * here — route_policy / query_understanding / extractor_rules / intent_strategy all sit
     * at the same level (no nesting under ontology/mining).
     */
    ServingDomainProfile parseProfile(String domainId, Map<String, Object> serving) {
        Map<String, Object> s = serving != null ? serving : Map.of();
        Map<String, Map<String, Map<String, Double>>> routePolicy = parseRoutePolicy(s);
        List<Map<String, Object>> extractorRules = toListOfMaps(s.get("extractor_rules"));
        @SuppressWarnings("unchecked")
        Map<String, Object> queryUnderstanding =
                s.get("query_understanding") instanceof Map<?, ?> qu ? (Map<String, Object>) qu : Map.of();
        @SuppressWarnings("unchecked")
        Map<String, Object> intentStrategy =
                s.get("intent_strategy") instanceof Map<?, ?> is ? (Map<String, Object>) is : Map.of();

        return new ServingDomainProfile(domainId, routePolicy, extractorRules, queryUnderstanding, intentStrategy);
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> toListOfMaps(Object obj) {
        if (obj instanceof List) return (List<Map<String, Object>>) obj;
        return List.of();
    }

    @SuppressWarnings("unchecked")
    private Map<String, Map<String, Map<String, Double>>> parseRoutePolicy(Map<String, Object> serving) {
        Object policy = serving.get("route_policy");
        if (policy == null) return ServingDomainProfile.defaults("default").routePolicy();

        Map<String, Map<String, Map<String, Double>>> result =
                new LinkedHashMap<>(ServingDomainProfile.defaults("default").routePolicy());

        Map<String, Object> policyMap = (Map<String, Object>) policy;
        for (var entry : policyMap.entrySet()) {
            String intent = entry.getKey();
            if (!(entry.getValue() instanceof Map<?, ?> routes)) continue;

            Map<String, Map<String, Double>> intentPolicy = new LinkedHashMap<>();
            for (var routeEntry : routes.entrySet()) {
                String routeName = String.valueOf(routeEntry.getKey());
                if (!(routeEntry.getValue() instanceof Map<?, ?> params)) continue;

                Map<String, Double> paramMap = new LinkedHashMap<>();
                for (var paramEntry : params.entrySet()) {
                    if (paramEntry.getValue() instanceof Number num) {
                        paramMap.put(String.valueOf(paramEntry.getKey()), num.doubleValue());
                    }
                }
                intentPolicy.put(routeName, Collections.unmodifiableMap(paramMap));
            }
            result.put(intent, Collections.unmodifiableMap(intentPolicy));
        }
        return Collections.unmodifiableMap(result);
    }
}
