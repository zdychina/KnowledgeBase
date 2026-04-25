package com.coremasterkb.serving.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "serving")
public class ServingProperties {

    private LlmService llmService = new LlmService();
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
        private String baseUrl = "http://localhost:8900";
        private boolean enabled = false;
        private int timeoutMs = 3000;

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

        public int getTimeoutMs() {
            return timeoutMs;
        }

        public void setTimeoutMs(int timeoutMs) {
            this.timeoutMs = timeoutMs;
        }
    }

    public static class Fts {
        private String strategy = "sqlite";

        public String getStrategy() {
            return strategy;
        }

        public void setStrategy(String strategy) {
            this.strategy = strategy;
        }
    }
}