package com.coremasterkb.serving;

import com.coremasterkb.serving.domain.ActiveScope;
import com.coremasterkb.serving.repository.AssetRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.SQLException;

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
    protected AssetRepository assetRepository;

    protected ActiveScope activeScope;

    @BeforeEach
    void ensurePgConnectionAndResolveScope() {
        boolean connectionOk = checkConnection();
        assumeTrue(connectionOk, "PostgreSQL not reachable — skipping PG integration test");

        try {
            this.activeScope = assetRepository.resolveActiveScope("cloud_core_network");
        } catch (Exception e) {
            assumeTrue(false, "Cannot resolve active scope for cloud_core_network: " + e.getMessage());
        }

        assumeTrue(activeScope.snapshotIds() != null && !activeScope.snapshotIds().isEmpty(),
                "No snapshot IDs found — skipping");
    }

    private boolean checkConnection() {
        try (Connection conn = dataSource.getConnection()) {
            return conn.isValid(3);
        } catch (SQLException e) {
            return false;
        }
    }
}
