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

    @NestedConfigurationProperty
    private Reranker reranker = new Reranker();

    @Data
    public static class Reranker {

        /** Multiplier applied to low-value block types (heading, toc, link). */
        private double lowValueBlockPenalty = 0.3;

        /** Score added when semantic_role matches a desired role. */
        private double boostSemanticRole = 0.30;

        /** Score added when block_type matches a desired block type. */
        private double boostBlockType = 0.15;

        /** Score added when scope constraints match the candidate's facets. */
        private double boostScopeMatch = 0.20;

        /** Score added when entity constraints match the candidate's entity refs. */
        private double boostEntityMatch = 0.25;
    }
}
