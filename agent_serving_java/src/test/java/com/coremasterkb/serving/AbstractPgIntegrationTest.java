package com.coremasterkb.serving;

import com.coremasterkb.serving.domain.ActiveScope;
import com.coremasterkb.serving.entity.AssetPublishRelease;
import com.coremasterkb.serving.mapper.AssetPublishReleaseMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.List;

import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * Base class for all PostgreSQL integration tests.
 *
 * <p>Features:
 * <ul>
 *   <li>Uses real PG via environment variables</li>
 *   <li>Gracefully skips if PG is unreachable</li>
 *   <li>Dynamically resolves active scope from live data</li>
 * </ul>
 */
@SpringBootTest(classes = AgentServingApplication.class)
@ActiveProfiles("test-pg")
@Tag("pg-integration")
public abstract class AbstractPgIntegrationTest {

    @Autowired
    protected DataSource dataSource;

    @Autowired
    protected AssetPublishReleaseMapper publishReleaseMapper;

    protected ActiveScope activeScope;

    @BeforeEach
    void ensurePgConnectionAndResolveScope() {
        boolean connectionOk = checkConnection();
        assumeTrue(connectionOk, "PostgreSQL not reachable — skipping PG integration test");

        List<AssetPublishRelease> releases =
                publishReleaseMapper.selectActiveByDomain("cloud_core_network");
        assumeTrue(releases != null && !releases.isEmpty(),
                "No active releases found for cloud_core_network — skipping");

        AssetPublishRelease release = releases.get(0);
        List<String> snapshotIds = List.of(); // will be populated from release data if available

        this.activeScope = new ActiveScope(
                release.getId() != null ? release.getId().toString() : "",
                release.getBuildId() != null ? release.getBuildId().toString() : "",
                snapshotIds,
                java.util.Map.of()
        );
    }

    private boolean checkConnection() {
        try (Connection conn = dataSource.getConnection()) {
            return conn.isValid(3);
        } catch (SQLException e) {
            return false;
        }
    }
}
