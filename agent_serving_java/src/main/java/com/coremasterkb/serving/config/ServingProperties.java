package com.coremasterkb.serving.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "serving")
public record ServingProperties(
    String scenarioPacksDir,
    String domainRegistryPath,
    String defaultDomain,
    LlmConfig llm,
    MainControl mainControl
) {
    public record LlmConfig(String baseUrl) {
        public LlmConfig {
            if (baseUrl == null) baseUrl = "";
        }
    }

    /** Config source: main_control's base URL (e.g. http://localhost:8910). */
    public record MainControl(String baseUrl) {
        public MainControl {
            if (baseUrl == null || baseUrl.isBlank()) baseUrl = "http://localhost:8910";
        }
    }

    public ServingProperties {
        // 域配置的真相源是 main_control（HTTP）。下面两个本地路径只是 main_control
        // 不可达时的兜底（IntelliJ / 测试），指向它所拥有的同一份文件。
        if (scenarioPacksDir == null) scenarioPacksDir = "../main_control_service/config/scenario_packs";
        if (domainRegistryPath == null) domainRegistryPath = "../main_control_service/config/domain_registry.yaml";
        if (defaultDomain == null) defaultDomain = "cloud_core_network";
        if (llm == null) llm = new LlmConfig("");
        if (mainControl == null) mainControl = new MainControl("http://localhost:8910");
    }
}
