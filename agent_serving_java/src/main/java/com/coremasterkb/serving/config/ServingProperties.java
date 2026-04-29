package com.coremasterkb.serving.config;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.NestedConfigurationProperty;
import org.springframework.validation.annotation.Validated;

import java.time.Duration;

@ConfigurationProperties(prefix = "serving")
@Validated
@Data
public class ServingProperties {

    @Valid
    @NestedConfigurationProperty
    private LlmService llmService = new LlmService();

    @Valid
    @NestedConfigurationProperty
    private Fts fts = new Fts();

    @Valid
    @NestedConfigurationProperty
    private Zhipu zhipu = new Zhipu();

    @Data
    public static class LlmService {

        @NotBlank
        private String baseUrl;

        private boolean enabled;

        @NotNull
        private Duration connectTimeout;

        @NotNull
        private Duration readTimeout;
    }

    @Data
    public static class Fts {

        @NotBlank
        private String strategy;
    }

    @Data
    public static class Zhipu {

        /** Zhipu API key. Leave blank to disable direct embedding calls. */
        private String apiKey = "";

        private String baseUrl = "https://open.bigmodel.cn/api/paas/v4";

        private String embeddingModel = "embedding-3";

        /** Dimension of the embedding vector (embedding-3 supports 64~2048). */
        private int embeddingDimensions = 2048;

        private String rerankModel = "rerank";

        public boolean isConfigured() {
            return apiKey != null && !apiKey.isBlank();
        }
    }
}
