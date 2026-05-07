package com.coremasterkb.serving.config;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.NestedConfigurationProperty;
import org.springframework.validation.annotation.Validated;

import java.time.Duration;
import java.util.Set;

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

    @NestedConfigurationProperty
    private Domain domain = new Domain();

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

        @NotBlank
        private String apiKey;

        private String baseUrl;

        private String embeddingModel;

        /** Dimension of the embedding vector (embedding-3 supports 64~2048). */
        private int embeddingDimensions;

        private String rerankModel;
    }

    @Data
    public static class Domain {

        private Set<String> products = Set.of("UDG", "UNC", "CloudCore");

        private Set<String> networkElements = Set.of(
                "AMF", "SMF", "UPF", "UDM", "PCF", "NRF",
                "AUSF", "BSF", "NSSF", "SCP", "UDSF", "UDR");
    }
}
