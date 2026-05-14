package com.coremasterkb.serving.observability;

import com.coremasterkb.serving.domain.*;
import com.coremasterkb.serving.entity.ServingQueryLog;
import com.coremasterkb.serving.mapper.ServingQueryLogMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;

@DisplayName("QueryLogService")
class QueryLogServiceTest {

    private ServingQueryLogMapper logMapper;
    private QueryLogService service;

    @BeforeEach
    void setUp() {
        logMapper = mock(ServingQueryLogMapper.class);
        service = new QueryLogService(logMapper);
    }

    private SearchRequest req(String query, String domain, String channel) {
        return new SearchRequest(query, Map.of(), List.of(), false, domain, channel, "evidence");
    }

    private ContextQuery ctxQuery(String intent, String source,
                                   String releaseId, String buildId, int snapshotCount) {
        return new ContextQuery("q", "q", intent, List.of(), Map.of(), List.of(),
                source, releaseId, buildId, snapshotCount);
    }

    private ContextPack packWith(ContextQuery q, List<ContextItem> items) {
        return new ContextPack(q, items, List.of(), List.of(), List.of(), List.of(), List.of(), Map.of());
    }

    @Nested
    @DisplayName("channel resolution")
    class ChannelResolution {
        @Test
        @DisplayName("uses explicit channel when provided")
        void usesExplicitChannel() {
            service.record("id1", req("q", "domain1", "beta"), null, 100);
            var captor = ArgumentCaptor.forClass(ServingQueryLog.class);
            verify(logMapper).insert(captor.capture());
            assertThat(captor.getValue().getChannel()).isEqualTo("beta");
        }

        @Test
        @DisplayName("falls back to 'prod' when channel is blank")
        void fallsBackToProd() {
            service.record("id2", req("q", "cloud_core_network", null), null, 100);
            var captor = ArgumentCaptor.forClass(ServingQueryLog.class);
            verify(logMapper).insert(captor.capture());
            assertThat(captor.getValue().getChannel()).isEqualTo("prod");
        }

        @Test
        @DisplayName("domain is stored separately from channel")
        void domainStoredSeparately() {
            service.record("id3", req("q", "cloud_core_network", null), null, 100);
            var captor = ArgumentCaptor.forClass(ServingQueryLog.class);
            verify(logMapper).insert(captor.capture());
            assertThat(captor.getValue().getDomain()).isEqualTo("cloud_core_network");
            assertThat(captor.getValue().getChannel()).isEqualTo("prod");
        }
    }

    @Nested
    @DisplayName("scope fields from ContextQuery")
    class ScopeFields {
        @Test
        @DisplayName("releaseId, buildId, snapshotCount, normalizerSource are populated from pack.query()")
        void scopeFieldsPopulated() {
            var q = ctxQuery("command_usage", "llm", "rel-42", "build-7", 3);
            var pack = packWith(q, List.of());

            service.record("id4", req("q", "d", "prod"), pack, 50);

            var captor = ArgumentCaptor.forClass(ServingQueryLog.class);
            verify(logMapper).insert(captor.capture());
            ServingQueryLog entry = captor.getValue();
            assertThat(entry.getReleaseId()).isEqualTo("rel-42");
            assertThat(entry.getBuildId()).isEqualTo("build-7");
            assertThat(entry.getSnapshotCount()).isEqualTo(3);
            assertThat(entry.getNormalizerSource()).isEqualTo("llm");
            assertThat(entry.getIntent()).isEqualTo("command_usage");
        }
    }

    @Nested
    @DisplayName("result fields")
    class ResultFields {
        @Test
        @DisplayName("seed count and hasResult computed correctly")
        void seedCount() {
            var item = new ContextItem("u1", "retrieval_unit", "seed", "text", 0.9,
                    null, "para", "unknown", null, null, Map.of(), Map.of(), List.of(), null, "", Map.of());
            var pack = packWith(ctxQuery("general", "rule", "", "", 1), List.of(item));

            service.record("id5", req("q", "d", "prod"), pack, 20);

            var captor = ArgumentCaptor.forClass(ServingQueryLog.class);
            verify(logMapper).insert(captor.capture());
            assertThat(captor.getValue().getResultSeedCount()).isEqualTo(1);
            assertThat(captor.getValue().getResultHasResult()).isTrue();
        }

        @Test
        @DisplayName("null pack sets hasResult=false and skips scope fields")
        void nullPack() {
            service.record("id6", req("q", "d", "prod"), null, 10);

            var captor = ArgumentCaptor.forClass(ServingQueryLog.class);
            verify(logMapper).insert(captor.capture());
            assertThat(captor.getValue().getResultHasResult()).isFalse();
            assertThat(captor.getValue().getReleaseId()).isNull();
        }
    }

    @Nested
    @DisplayName("failure isolation")
    class FailureIsolation {
        @Test
        @DisplayName("mapper failure is swallowed — no exception propagates")
        void mapperFailureSwallowed() {
            doThrow(new RuntimeException("db down")).when(logMapper).insert(any());
            // should not throw
            service.record("id7", req("q", "d", "prod"), null, 10);
        }
    }
}
