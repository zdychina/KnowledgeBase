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

    @Data
    public static class LlmService {

        @NotBlank
        private String baseUrl = "http://localhost:8900";

        private boolean enabled = false;

        @NotNull
        private Duration timeout = Duration.ofMillis(3000);
    }

    @Data
    public static class Fts {

        @NotBlank
        private String strategy = "sqlite";
    }
}
