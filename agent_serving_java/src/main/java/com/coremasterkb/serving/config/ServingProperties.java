package com.coremasterkb.serving.config;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.NestedConfigurationProperty;
import org.springframework.validation.annotation.Validated;

import java.time.Duration;

@ConfigurationProperties(prefix = "serving")
@Validated
public class ServingProperties {

    @Valid
    @NestedConfigurationProperty
    private LlmService llmService = new LlmService();

    @Valid
    @NestedConfigurationProperty
    private Fts fts = new Fts();

    public LlmService getLlmService() {
        return llmService;
    }

    public void setLlmService(LlmService llmService) {
        this.llmService = llmService;
    }

    public Fts getFts() {
        return fts;
    }

    public void setFts(Fts fts) {
        this.fts = fts;
    }

    public static class LlmService {

        @NotBlank
        private String baseUrl = "http://localhost:8900";

        private boolean enabled = false;

        @NotNull
        private Duration timeout = Duration.ofMillis(3000);

        public String getBaseUrl() {
            return baseUrl;
        }

        public void setBaseUrl(String baseUrl) {
            this.baseUrl = baseUrl;
        }

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public Duration getTimeout() {
            return timeout;
        }

        public void setTimeout(Duration timeout) {
            this.timeout = timeout;
        }
    }

    public static class Fts {

        @NotBlank
        private String strategy = "sqlite";

        public String getStrategy() {
            return strategy;
        }

        public void setStrategy(String strategy) {
            this.strategy = strategy;
        }
    }
}
