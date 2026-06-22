package com.coremasterkb.serving.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "serving")
public record ServingProperties(
    String scenarioPacksDir,
    String domainRegistryPath,
    String defaultDomain,
    LlmConfig llm
) {
    public record LlmConfig(String baseUrl) {
        public LlmConfig {
            if (baseUrl == null) baseUrl = "";
        }
    }

    public ServingProperties {
        if (scenarioPacksDir == null) scenarioPacksDir = "../scenario_packs";
        if (domainRegistryPath == null) domainRegistryPath = "../domain_registry.yaml";
        if (defaultDomain == null) defaultDomain = "cloud_core_network";
        if (llm == null) llm = new LlmConfig("");
    }
}
