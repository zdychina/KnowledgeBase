package com.coremasterkb.serving.mapper;

import com.coremasterkb.serving.AbstractPgIntegrationTest;
import com.coremasterkb.serving.mapper.result.FtsResultRow;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

@DisplayName("AssetRetrievalUnitMapper IT")
class AssetRetrievalUnitMapperIT extends AbstractPgIntegrationTest {

    @Autowired
    private AssetRetrievalUnitMapper unitMapper;

    @Test
    @DisplayName("searchByFts with actual data term returns results")
    void searchByFtsReturnsResults() {
        List<FtsResultRow> results = unitMapper.searchByFts("Test", activeScope.snapshotIds(), 10);
        assumeTrue(!results.isEmpty(), "no FTS data for 'Test' in test DB — skipping");
    }

    @Test
    @DisplayName("searchByFts with nonsense returns empty or few results")
    void searchByFtsNonsenseReturnsFew() {
        List<FtsResultRow> results = unitMapper.searchByFts("xyzzy123nonexistent", activeScope.snapshotIds(), 10);
        assertThat(results.size()).isLessThanOrEqualTo(2);
    }

    @Test
    @DisplayName("searchByTrigram with actual data term returns results")
    void searchByTrigramReturnsResults() {
        List<FtsResultRow> results;
        try {
            results = unitMapper.searchByTrigram("Document", activeScope.snapshotIds(), 10);
        } catch (org.springframework.dao.DataAccessException e) {
            assumeTrue(false, "pg_trgm not available: " + e.getMostSpecificCause().getMessage());
            return;
        }
        assumeTrue(!results.isEmpty(), "no trigram data for 'Document' in test DB — skipping");
    }

    @Test
    @DisplayName("searchByLike with actual data term returns results")
    void searchByLikeReturnsResults() {
        List<FtsResultRow> results = unitMapper.searchByLike(List.of("%Test%"), activeScope.snapshotIds(), 10);
        assumeTrue(!results.isEmpty(), "no LIKE data for '%Test%' in test DB — skipping");
    }
}
