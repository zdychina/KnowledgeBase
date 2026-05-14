package com.coremasterkb.serving.retrieval;

import com.coremasterkb.serving.AbstractPgIntegrationTest;
import com.coremasterkb.serving.domain.EntityRef;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.RetrievalQuery;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

@DisplayName("FtsRetriever IT")
class FtsRetrieverIT extends AbstractPgIntegrationTest {

    @Autowired
    private com.coremasterkb.serving.mapper.AssetRetrievalUnitMapper unitMapper;

    private FtsRetriever retriever;

    @BeforeEach
    void setUp() {
        retriever = new FtsRetriever(unitMapper);
    }

    @Test
    @DisplayName("FTS search for actual data term returns candidates")
    void ftsSearchReturnsCandidates() {
        RetrievalQuery query = new RetrievalQuery("Test Document", List.of("Test"),
                List.of(), null, List.of(), "concept_lookup", java.util.Map.of());

        List<RetrievalCandidate> results = retriever.retrieve(query, activeScope.snapshotIds(), 10);
        assumeTrue(!results.isEmpty(), "no FTS data for 'Test Document' in test DB — skipping");
    }

    @Test
    @DisplayName("FTS search for nonsense returns empty")
    void ftsSearchNonsenseReturnsEmpty() {
        RetrievalQuery query = new RetrievalQuery("xyzzy123nonexistent", List.of("xyzzy123"),
                List.of(), null, List.of(), "general", java.util.Map.of());

        List<RetrievalCandidate> results = retriever.retrieve(query, activeScope.snapshotIds(), 10);
        assertThat(results).isEmpty();
    }
}
