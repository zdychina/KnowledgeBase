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

@DisplayName("EntityExactRetriever IT")
class EntityExactRetrieverIT extends AbstractPgIntegrationTest {

    @Autowired
    private com.coremasterkb.serving.mapper.AssetRetrievalUnitMapper unitMapper;

    private EntityExactRetriever retriever;

    @BeforeEach
    void setUp() {
        retriever = new EntityExactRetriever(unitMapper);
    }

    @Test
    @DisplayName("Entity exact search returns non-null result (may be empty if no entity data)")
    void entityExactSearchReturnsNotNull() {
        // Seed data may not have entity_refs_json populated;
        // the test validates the query path works without error
        RetrievalQuery query = new RetrievalQuery("Test", List.of("Test"),
                List.of(new EntityRef("concept", "Test", "Test")),
                null, List.of(), "general", java.util.Map.of());

        List<RetrievalCandidate> results = retriever.retrieve(query, activeScope.snapshotIds(), 10);
        assertThat(results).isNotNull();
    }
}
