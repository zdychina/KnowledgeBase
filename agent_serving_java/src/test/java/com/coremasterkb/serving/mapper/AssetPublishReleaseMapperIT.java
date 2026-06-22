package com.coremasterkb.serving.mapper;

import com.coremasterkb.serving.AbstractPgIntegrationTest;
import com.coremasterkb.serving.entity.AssetPublishRelease;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("AssetPublishReleaseMapper IT")
class AssetPublishReleaseMapperIT extends AbstractPgIntegrationTest {

    @Autowired
    private AssetPublishReleaseMapper publishReleaseMapper;

    @Test
    @DisplayName("selectActiveByDomain(cloud_core_network) returns at least 1 release")
    void activeReleaseForCloudCore() {
        List<AssetPublishRelease> releases = publishReleaseMapper.selectActiveByDomain("cloud_core_network");
        assertThat(releases).isNotEmpty();
        assertThat(releases.get(0).getDomain()).isEqualTo("cloud_core_network");
    }

    @Test
    @DisplayName("selectActiveByDomain(nonexistent) returns empty list")
    void noReleaseForNonexistentDomain() {
        List<AssetPublishRelease> releases = publishReleaseMapper.selectActiveByDomain("nonexistent_domain_xyz");
        assertThat(releases).isEmpty();
    }
}
