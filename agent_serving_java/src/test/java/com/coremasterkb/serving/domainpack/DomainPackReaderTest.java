package com.coremasterkb.serving.domainpack;

import com.coremasterkb.serving.config.ServingProperties;
import com.coremasterkb.serving.domainpack.ServingConfigSnapshot.DomainConfig;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.*;

@DisplayName("DomainPackReader")
class DomainPackReaderTest {

    private DomainRegistry mockRegistry(boolean loaded) {
        DomainRegistry reg = mock(DomainRegistry.class);
        when(reg.isLoaded()).thenReturn(loaded);
        when(reg.resolve(anyString())).thenReturn(null);
        return reg;
    }

    private ServingProperties props() {
        ServingProperties p = mock(ServingProperties.class);
        when(p.defaultDomain()).thenReturn("generic");
        return p;
    }

    /** Build a one-domain snapshot carrying the given scenario-pack {@code serving:} block. */
    private static ServingConfigSnapshot snapshotOf(String domainId, Map<String, Object> serving) {
        return new ServingConfigSnapshot(Map.of(
                domainId, new DomainConfig(domainId, true, "prod", null, serving)));
    }

    @Nested
    @DisplayName("empty snapshot")
    class EmptySnapshot {
        @Test
        @DisplayName("returns defaults when no config has been applied")
        void returnsDefaultsWhenNothingApplied() {
            var reader = new DomainPackReader(props(), mockRegistry(false));

            var profile = reader.getProfile("generic");
            assertThat(profile).isNotNull();
            assertThat(profile.routePolicy()).isNotEmpty();
        }
    }

    @Nested
    @DisplayName("serving block parsing")
    class ServingBlockParsing {

        @Test
        @DisplayName("extractor_rules regex patterns compile without error")
        void extractorRuleRegexCompiles() {
            // mirrors the cloud_core_network domain.yaml serving.extractor_rules
            var reader = new DomainPackReader(props(), mockRegistry(false));
            reader.apply(snapshotOf("ccn", Map.of(
                    "extractor_rules", List.of(
                            Map.of("pattern", "\\b(AMF|SMF|UPF|UDM|PCF|NRF|AUSF|BSF|NSSF|SCP|UDSF|UDR)\\b",
                                    "entity_type", "network_function"),
                            Map.of("pattern", "\\b(N[1-9]|N1[0-9]|Xn|Uu|NG-RAN)\\b",
                                    "entity_type", "interface"),
                            Map.of("pattern", "\\b(PFCP|GTP-U|HTTP/2|SBI|TLS|IPSec|NAS)\\b",
                                    "entity_type", "protocol")))));

            var profile = reader.getProfile("ccn");
            assertThat(profile.extractorRules()).hasSize(3);
            for (var rule : profile.extractorRules()) {
                String pat = (String) rule.get("pattern");
                assertThat(pat).isNotNull();
                Pattern.compile(pat); // throws PatternSyntaxException if invalid
            }
            String nfPattern = (String) profile.extractorRules().get(0).get("pattern");
            assertThat(Pattern.compile(nfPattern).matcher("SMF配置").find()).isTrue();
        }

        @Test
        @DisplayName("route_policy overrides are loaded per intent")
        void routePolicyLoaded() {
            var reader = new DomainPackReader(props(), mockRegistry(false));
            reader.apply(snapshotOf("d1", Map.of(
                    "route_policy", Map.of(
                            "command_usage", Map.of(
                                    "entity_exact", Map.of("weight", 1.6, "top_k", 20),
                                    "lexical_bm25", Map.of("weight", 1.0, "top_k", 50))))));

            var profile = reader.getProfile("d1");
            var cmdPolicy = profile.getRoutePolicyForIntent("command_usage");
            assertThat(cmdPolicy).containsKey("entity_exact");
            assertThat(cmdPolicy.get("entity_exact").get("weight")).isEqualTo(1.6);
            assertThat(cmdPolicy.get("entity_exact").get("top_k")).isEqualTo(20.0);
        }

        @Test
        @DisplayName("intents absent from the pack keep their built-in defaults")
        void unspecifiedIntentsFallBackToDefaults() {
            var reader = new DomainPackReader(props(), mockRegistry(false));
            reader.apply(snapshotOf("d1", Map.of(
                    "route_policy", Map.of(
                            "command_usage", Map.of("entity_exact", Map.of("weight", 1.6))))));

            var profile = reader.getProfile("d1");
            assertThat(profile.getRoutePolicyForIntent("concept_lookup")).containsKey("dense_vector");
        }

        @Test
        @DisplayName("an empty serving block yields the default route policy")
        void emptyServingBlockYieldsDefaults() {
            var reader = new DomainPackReader(props(), mockRegistry(false));
            reader.apply(snapshotOf("d1", Map.of()));

            var profile = reader.getProfile("d1");
            assertThat(profile.routePolicy()).isNotEmpty();
            assertThat(profile.extractorRules()).isEmpty();
        }
    }

    @Nested
    @DisplayName("apply replaces the previous view")
    class ApplyReplaces {
        @Test
        @DisplayName("a domain dropped from the snapshot is no longer served")
        void reloadDropsRemovedDomain() {
            var reader = new DomainPackReader(props(), mockRegistry(false));
            reader.apply(snapshotOf("d1", Map.of()));
            assertThat(reader.getProfile("d1").domainId()).isEqualTo("d1");

            reader.apply(snapshotOf("d2", Map.of()));

            // d1 is gone from the cache; registry is lenient here, so an unknown domain
            // with a non-empty cache is reported as unknown_domain.
            assertThatThrownBy(() -> reader.getProfile("d1"))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessage("unknown_domain");
        }
    }

    @Nested
    @DisplayName("domain validation")
    class DomainValidation {
        @Test
        @DisplayName("unknown_domain thrown when registry is loaded and domain not found")
        void unknownDomainThrown() {
            DomainRegistry reg = mock(DomainRegistry.class);
            when(reg.isLoaded()).thenReturn(true);
            when(reg.resolve("unknown")).thenThrow(new IllegalArgumentException("unknown_domain"));

            var reader = new DomainPackReader(props(), reg);

            assertThatThrownBy(() -> reader.getProfile("unknown"))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessage("unknown_domain");
        }
    }
}
