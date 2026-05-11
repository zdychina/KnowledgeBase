package com.coremasterkb.serving.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "serving")
public record ServingProperties(
    String scenarioPacksDir,
    String defaultDomain,
    LlmConfig llm,
    ZhipuConfig zhipu,
    EmbeddingConfig embedding
) {
    public record LlmConfig(String baseUrl, String apiKey) {
        public LlmConfig {
            if (baseUrl == null) baseUrl = "";
            if (apiKey == null) apiKey = "";
        }
    }

    public record ZhipuConfig(String apiKey, String baseUrl, String rerankModel) {
        public ZhipuConfig {
            if (baseUrl == null) baseUrl = "";
            if (rerankModel == null) rerankModel = "";
            if (apiKey == null) apiKey = "";
        }
    }

    public record EmbeddingConfig(String model, int dimensions) {
        public EmbeddingConfig {
            if (model == null) model = "";
        }
    }

    public ServingProperties {
        if (scenarioPacksDir == null) scenarioPacksDir = "../scenario_packs";
        if (defaultDomain == null) defaultDomain = "cloud_core_network";
        if (llm == null) llm = new LlmConfig("", "");
        if (zhipu == null) zhipu = new ZhipuConfig("", "", "");
        if (embedding == null) embedding = new EmbeddingConfig("", 1024);
    }
}
