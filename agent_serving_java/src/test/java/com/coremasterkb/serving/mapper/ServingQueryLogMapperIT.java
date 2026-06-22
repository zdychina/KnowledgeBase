package com.coremasterkb.serving.mapper;

import com.coremasterkb.serving.AgentServingApplication;
import com.coremasterkb.serving.entity.ServingQueryLog;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.SQLException;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

@SpringBootTest(classes = AgentServingApplication.class)
@ActiveProfiles("test-pg")
@Tag("pg-integration")
@DisplayName("ServingQueryLogMapper IT")
class ServingQueryLogMapperIT {

    @Autowired
    private DataSource dataSource;

    @Autowired
    private ServingQueryLogMapper mapper;

    private JdbcTemplate jdbc;
    private String testId;

    @BeforeEach
    void setUp() {
        try (Connection conn = dataSource.getConnection()) {
            assumeTrue(conn.isValid(3), "PostgreSQL not reachable — skipping");
        } catch (SQLException e) {
            assumeTrue(false, "PostgreSQL not reachable — skipping");
        }
        jdbc = new JdbcTemplate(dataSource);
        testId = "test-" + UUID.randomUUID();
    }

    @AfterEach
    void cleanUp() {
        if (jdbc != null && testId != null) {
            jdbc.update("DELETE FROM serving_query_logs WHERE id = ?", testId);
        }
    }

    @Test
    @DisplayName("insert persists all columns correctly")
    void insertAllColumns() {
        ServingQueryLog entry = buildFullEntry(testId);
        mapper.insert(entry);

        Map<String, Object> row = jdbc.queryForMap(
                "SELECT * FROM serving_query_logs WHERE id = ?", testId);

        assertThat(row.get("id")).isEqualTo(testId);
        assertThat(row.get("query_text")).isEqualTo("SMF配置查询");
        assertThat(row.get("domain")).isEqualTo("cloud_core_network");
        assertThat(row.get("channel")).isEqualTo("prod");
        assertThat(row.get("intent")).isEqualTo("command_usage");
        assertThat(row.get("normalizer_source")).isEqualTo("llm");
        assertThat(row.get("release_id")).isEqualTo("rel-1");
        assertThat(row.get("build_id")).isEqualTo("build-42");
        assertThat(row.get("snapshot_count")).isEqualTo(3);
        assertThat(row.get("result_item_count")).isEqualTo(5);
        assertThat(row.get("result_seed_count")).isEqualTo(2);
        assertThat(row.get("result_has_result")).isEqualTo(true);
        assertThat(row.get("duration_ms")).isEqualTo(120);
        assertThat(row.get("keywords_json")).isEqualTo("[\"SMF\",\"配置\"]");
        assertThat(row.get("scope_json")).isEqualTo("{\"product\":\"UNC\"}");
        assertThat(row.get("metadata_json")).isEqualTo("{}");
    }

    @Test
    @DisplayName("insert with null optional fields succeeds")
    void insertWithNullOptionals() {
        ServingQueryLog entry = new ServingQueryLog();
        entry.setId(testId);
        entry.setQueryText("minimal query");
        entry.setDomain("default");
        entry.setChannel("default");
        entry.setQueriedAt(Instant.now().toString());
        entry.setMetadataJson("{}");
        entry.setKeywordsJson("[]");
        entry.setEntitiesJson("[]");
        entry.setScopeJson("{}");
        entry.setResultIssuesJson("[]");
        entry.setResultItemsJson("[]");
        entry.setResultSourcesJson("[]");
        entry.setResultRelationsJson("[]");
        entry.setResultHasResult(false);

        mapper.insert(entry);

        Map<String, Object> row = jdbc.queryForMap(
                "SELECT id, query_text, intent, release_id FROM serving_query_logs WHERE id = ?", testId);

        assertThat(row.get("id")).isEqualTo(testId);
        assertThat(row.get("intent")).isNull();
        assertThat(row.get("release_id")).isNull();
    }

    // -------------------------------------------------------------------------

    private ServingQueryLog buildFullEntry(String id) {
        ServingQueryLog e = new ServingQueryLog();
        e.setId(id);
        e.setQueryText("SMF配置查询");
        e.setDomain("cloud_core_network");
        e.setChannel("prod");
        e.setIntent("command_usage");
        e.setNormalizerSource("llm");
        e.setKeywordsJson("[\"SMF\",\"配置\"]");
        e.setEntitiesJson("[{\"type\":\"network_function\",\"name\":\"SMF\"}]");
        e.setScopeJson("{\"product\":\"UNC\"}");
        e.setReleaseId("rel-1");
        e.setBuildId("build-42");
        e.setSnapshotCount(3);
        e.setResultItemCount(5);
        e.setResultSeedCount(2);
        e.setResultHasResult(true);
        e.setResultIssuesJson("[]");
        e.setResultItemsJson("[{\"id\":\"u1\",\"score\":0.9}]");
        e.setResultSourcesJson("[{\"id\":\"doc1\"}]");
        e.setResultRelationsJson("[]");
        e.setDurationMs(120);
        e.setQueriedAt(Instant.now().toString());
        e.setMetadataJson("{}");
        return e;
    }
}
