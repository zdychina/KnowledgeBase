package com.coremasterkb.serving.domainpack;

import com.coremasterkb.serving.config.ServingProperties;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.yaml.snakeyaml.Yaml;

import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

@Component
public class DomainPackReader {

    private static final Logger log = LoggerFactory.getLogger(DomainPackReader.class);

    private final Map<String, ServingDomainProfile> cache = new ConcurrentHashMap<>();
    private final String packsDir;
    private final String defaultDomain;
    private final DomainRegistry domainRegistry;
    /** True only when the packs directory was found and scanned at startup. */
    private boolean packsDirectoryFound = false;

    public DomainPackReader(ServingProperties props, DomainRegistry domainRegistry) {
        this.packsDir = props.scenarioPacksDir();
        this.defaultDomain = props.defaultDomain();
        this.domainRegistry = domainRegistry;
    }

    @PostConstruct
    public void init() {
        Path root = Paths.get(packsDir);
        if (!Files.isDirectory(root)) {
            log.info("Scenario packs directory not found: {}, using defaults", packsDir);
            return;
        }
        packsDirectoryFound = true;
        try (var dirs = Files.list(root)) {
            dirs.filter(Files::isDirectory).forEach(dir -> {
                Path yamlPath = dir.resolve("domain.yaml");
                if (Files.exists(yamlPath)) {
                    String domainId = dir.getFileName().toString();
                    try {
                        ServingDomainProfile profile = parseYaml(domainId, yamlPath);
                        cache.put(domainId, profile);
                        log.info("Loaded domain pack: {}", domainId);
                    } catch (Exception e) {
                        log.warn("Failed to parse domain pack {}: {}", domainId, e.getMessage());
                    }
                }
            });
        } catch (Exception e) {
            log.warn("Failed to scan scenario packs directory: {}", e.getMessage());
        }
    }

    public ServingDomainProfile getProfile(String domainId) {
        String effectiveDomain = (domainId == null || domainId.isBlank()) ? defaultDomain : domainId;

        // Registry validation: throws unknown_domain / domain_disabled if registry is loaded
        domainRegistry.resolve(effectiveDomain);

        ServingDomainProfile profile = cache.get(effectiveDomain);
        if (profile != null) {
            return profile;
        }

        // Registry not loaded, fall back to cache-based enforcement
        if (!domainRegistry.isLoaded() && !cache.isEmpty()) {
            log.warn("Unknown domain '{}', known domains: {}", effectiveDomain, cache.keySet());
            throw new IllegalArgumentException("unknown_domain");
        }

        // Registry IS loaded and packs directory was found — missing pack is a deployment error
        if (domainRegistry.isLoaded() && packsDirectoryFound) {
            log.error("Scenario pack missing for domain '{}' — packs directory '{}' was scanned but no pack found",
                    effectiveDomain, packsDir);
            throw new IllegalStateException("scenario_pack_missing");
        }

        log.debug("No scenario pack for domain '{}', using defaults", effectiveDomain);
        return ServingDomainProfile.defaults(effectiveDomain);
    }

    private ServingDomainProfile parseYaml(String domainId, Path yamlPath) throws IOException {
        Yaml yaml = new Yaml();
        try (InputStream is = Files.newInputStream(yamlPath)) {
            Map<String, Object> data = yaml.load(is);

            Set<String> entityTypes = toSet(data.get("entity_types"));
            Set<String> strongEntityTypes = toSet(data.get("strong_entity_types"));
            List<Map<String, Object>> extractorRules = toListOfMaps(data.get("extractor_rules"));
            List<Map<String, Object>> evalQuestions = toListOfMaps(data.get("eval_questions"));

            @SuppressWarnings("unchecked")
            Map<String, Object> serving = (Map<String, Object>) data.getOrDefault("serving", Map.of());
            Map<String, Map<String, Map<String, Double>>> routePolicy = parseRoutePolicy(serving);
            @SuppressWarnings("unchecked")
            Map<String, Object> queryUnderstanding =
                    (Map<String, Object>) serving.getOrDefault("query_understanding", Map.of());

            return new ServingDomainProfile(
                    domainId, entityTypes, strongEntityTypes, routePolicy,
                    extractorRules, evalQuestions, queryUnderstanding
            );
        }
    }

    @SuppressWarnings("unchecked")
    private Set<String> toSet(Object obj) {
        if (obj instanceof List) return new HashSet<>((List<String>) obj);
        return Set.of();
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
