package com.coremasterkb.serving.domainpack;

import com.coremasterkb.serving.config.ServingProperties;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
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

    private ServingProperties propsWithDir(String dir) {
        ServingProperties props = mock(ServingProperties.class);
        when(props.scenarioPacksDir()).thenReturn(dir);
        when(props.defaultDomain()).thenReturn("generic");
        return props;
    }

    @Nested
    @DisplayName("missing packs directory")
    class MissingDirectory {
        @Test
        @DisplayName("returns defaults when directory does not exist")
        void returnsDefaultsWhenDirMissing() {
            var reader = new DomainPackReader(propsWithDir("/nonexistent/path"), mockRegistry(false));
            reader.init();

            var profile = reader.getProfile("generic");
            assertThat(profile).isNotNull();
            assertThat(profile.routePolicy()).isNotEmpty();
        }
    }

    @Nested
    @DisplayName("domain.yaml parsing")
    class YamlParsing {

        @Test
        @DisplayName("parses entity_types and strong_entity_types")
        void parsesEntityTypes(@TempDir Path tmpDir) throws IOException {
            writePackYaml(tmpDir, "testdomain", """
                    entity_types:
                      - command
                      - network_function
                    strong_entity_types:
                      - command
                    serving:
                      route_policy:
                        default:
                          lexical_bm25:
                            weight: 1.0
                            top_k: 50
                    """);

            var reader = new DomainPackReader(propsWithDir(tmpDir.toString()), mockRegistry(false));
            reader.init();

            var profile = reader.getProfile("testdomain");
            assertThat(profile.entityTypes()).containsExactlyInAnyOrder("command", "network_function");
            assertThat(profile.strongEntityTypes()).containsExactly("command");
        }

        @Test
        @DisplayName("extractor_rules regex patterns compile without error")
        void extractorRuleRegexCompiles(@TempDir Path tmpDir) throws IOException {
            // mirrors the cloud_core_network domain.yaml extractor_rules
            writePackYaml(tmpDir, "ccn", """
                    extractor_rules:
                      - pattern: "\\\\b(AMF|SMF|UPF|UDM|PCF|NRF|AUSF|BSF|NSSF|SCP|UDSF|UDR)\\\\b"
                        entity_type: network_function
                      - pattern: "\\\\b(N[1-9]|N1[0-9]|Xn|Uu|NG-RAN)\\\\b"
                        entity_type: interface
                      - pattern: "\\\\b(PFCP|GTP-U|HTTP/2|SBI|TLS|IPSec|NAS)\\\\b"
                        entity_type: protocol
                    """);

            var reader = new DomainPackReader(propsWithDir(tmpDir.toString()), mockRegistry(false));
            reader.init();

            var profile = reader.getProfile("ccn");
            assertThat(profile.extractorRules()).hasSize(3);
            // verify each pattern actually compiles and matches
            for (var rule : profile.extractorRules()) {
                String pat = (String) rule.get("pattern");
                assertThat(pat).isNotNull();
                Pattern.compile(pat); // throws PatternSyntaxException if invalid
            }
            // spot-check: NF pattern matches "SMF"
            String nfPattern = (String) profile.extractorRules().get(0).get("pattern");
            assertThat(Pattern.compile(nfPattern).matcher("SMF配置").find()).isTrue();
        }

        @Test
        @DisplayName("serving.route_policy overrides are loaded per intent")
        void routePolicyLoaded(@TempDir Path tmpDir) throws IOException {
            writePackYaml(tmpDir, "d1", """
                    serving:
                      route_policy:
                        command_usage:
                          entity_exact:
                            weight: 1.6
                            top_k: 20
                          lexical_bm25:
                            weight: 1.0
                            top_k: 50
                    """);

            var reader = new DomainPackReader(propsWithDir(tmpDir.toString()), mockRegistry(false));
            reader.init();

            var profile = reader.getProfile("d1");
            var cmdPolicy = profile.getRoutePolicyForIntent("command_usage");
            assertThat(cmdPolicy).containsKey("entity_exact");
            assertThat(cmdPolicy.get("entity_exact").get("weight")).isEqualTo(1.6);
            assertThat(cmdPolicy.get("entity_exact").get("top_k")).isEqualTo(20.0);
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

            var reader = new DomainPackReader(propsWithDir("/nonexistent"), reg);
            reader.init();

            assertThatThrownBy(() -> reader.getProfile("unknown"))
                    .isInstanceOf(IllegalArgumentException.class)
                    .hasMessage("unknown_domain");
        }
    }

    // -------------------------------------------------------------------------

    private void writePackYaml(Path baseDir, String domain, String yaml) throws IOException {
        Path domainDir = baseDir.resolve(domain);
        Files.createDirectories(domainDir);
        Files.writeString(domainDir.resolve("domain.yaml"), yaml);
    }
}
