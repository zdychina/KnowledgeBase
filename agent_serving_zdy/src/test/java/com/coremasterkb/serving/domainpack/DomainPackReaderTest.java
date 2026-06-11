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
import static org.mockito.ArgumentMatchers.anyString;
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
        ServingProperties props = mock(ServingProperties.class);
        when(props.defaultDomain()).thenReturn("generic");
        return props;
    }

    private ServingConfigSnapshot snapshot(String domain, Map<String, Object> serving) {
        return new ServingConfigSnapshot(Map.of(
                domain, new DomainConfig(domain, true, "prod", null, serving)));
    }

    @Nested
    @DisplayName("nothing applied")
    class Empty {
        @Test
        @DisplayName("returns defaults for the default domain")
        void returnsDefaults() {
            var reader = new DomainPackReader(props(), mockRegistry(false));

            var profile = reader.getProfile("generic");
            assertThat(profile).isNotNull();
            assertThat(profile.routePolicy()).isNotEmpty();
        }
    }

    @Nested
    @DisplayName("serving block parsing")
    class Parsing {

        @Test
        @DisplayName("extractor_rules from the serving block are loaded and compile")
        void extractorRules() {
            Map<String, Object> serving = Map.of("extractor_rules", List.of(
                    Map.of("pattern", "\\b(AMF|SMF|UPF)\\b", "entity_type", "network_function"),
                    Map.of("pattern", "\\b(N[1-9])\\b", "entity_type", "interface")));

            var reader = new DomainPackReader(props(), mockRegistry(false));
            reader.apply(snapshot("ccn", serving));

            var profile = reader.getProfile("ccn");
            assertThat(profile.extractorRules()).hasSize(2);
            for (var rule : profile.extractorRules()) {
                Pattern.compile((String) rule.get("pattern")); // throws if invalid
            }
            String nf = (String) profile.extractorRules().get(0).get("pattern");
            assertThat(Pattern.compile(nf).matcher("SMF配置").find()).isTrue();
        }

        @Test
        @DisplayName("route_policy overrides are loaded per intent")
        void routePolicy() {
            Map<String, Object> serving = Map.of("route_policy", Map.of(
                    "command_usage", Map.of(
                            "entity_exact", Map.of("weight", 1.6, "top_k", 20),
                            "lexical_bm25", Map.of("weight", 1.0, "top_k", 50))));

            var reader = new DomainPackReader(props(), mockRegistry(false));
            reader.apply(snapshot("d1", serving));

            var cmd = reader.getProfile("d1").getRoutePolicyForIntent("command_usage");
            assertThat(cmd).containsKey("entity_exact");
            assertThat(cmd.get("entity_exact").get("weight")).isEqualTo(1.6);
            assertThat(cmd.get("entity_exact").get("top_k")).isEqualTo(20.0);
        }

        @Test
        @DisplayName("query_understanding overrides are exposed on the profile")
        void queryUnderstanding() {
            Map<String, Object> serving = Map.of("query_understanding", Map.of(
                    "command_regex", "(ADD|MOD)\\s+(\\w+)",
                    "network_elements", List.of("SMF", "UPF")));

            var reader = new DomainPackReader(props(), mockRegistry(false));
            reader.apply(snapshot("d2", serving));

            var qu = reader.getProfile("d2").queryUnderstanding();
            assertThat(qu).containsKey("command_regex");
            @SuppressWarnings("unchecked")
            List<String> ne = (List<String>) qu.get("network_elements");
            assertThat(ne).contains("SMF", "UPF");
        }
    }

    @Nested
    @DisplayName("domain validation")
    class Validation {
        @Test
        @DisplayName("unknown_domain propagated from registry.resolve")
        void unknownDomain() {
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
