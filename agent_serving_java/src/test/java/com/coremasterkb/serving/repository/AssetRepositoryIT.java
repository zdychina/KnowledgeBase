package com.coremasterkb.serving.repository;

import com.coremasterkb.serving.AbstractPgIntegrationTest;
import com.coremasterkb.serving.domain.ActiveScope;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@DisplayName("AssetRepository IT")
class AssetRepositoryIT extends AbstractPgIntegrationTest {

    @Autowired
    private AssetRepository assetRepository;

    @Test
    @DisplayName("resolveActiveScope(cloud_core_network) returns valid scope")
    void resolveActiveScopeSuccess() {
        ActiveScope scope = assetRepository.resolveActiveScope("cloud_core_network");
        assertThat(scope.releaseId()).isNotNull();
        assertThat(scope.buildId()).isNotNull();
        assertThat(scope.snapshotIds()).isNotEmpty();
    }

    @Test
    @DisplayName("resolveActiveScope(nonexistent) throws no_active_release")
    void resolveActiveScopeThrowsForNonexistent() {
        assertThatThrownBy(() -> assetRepository.resolveActiveScope("nonexistent_domain_xyz"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("no_active_release");
    }
}
