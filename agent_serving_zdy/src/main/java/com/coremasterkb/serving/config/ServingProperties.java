package com.coremasterkb.serving.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "serving")
public record ServingProperties(
    String scenarioPacksDir,
    String domainRegistryPath,
    String defaultDomain,
    LlmConfig llm,
    EmbeddingConfig embedding,
    RerankConfig rerank
) {
    public record LlmConfig(String baseUrl) {
        public LlmConfig {
            if (baseUrl == null) baseUrl = "";
        }
    }

    public record EmbeddingConfig(String model, int dimensions) {
        public EmbeddingConfig {
            if (model == null) model = "";
        }
    }

    public record RerankConfig(String model) {
        public RerankConfig {
            if (model == null) model = "rerank-pro";
        }
    }

    public ServingProperties {
        if (scenarioPacksDir == null) scenarioPacksDir = "../scenario_packs";
        if (domainRegistryPath == null) domainRegistryPath = "../domain_registry.yaml";
        if (defaultDomain == null) defaultDomain = "cloud_core_network";
        if (llm == null) llm = new LlmConfig("");
        if (embedding == null) embedding = new EmbeddingConfig("", 1024);
        if (rerank == null) rerank = new RerankConfig("rerank-pro");
    }
}
