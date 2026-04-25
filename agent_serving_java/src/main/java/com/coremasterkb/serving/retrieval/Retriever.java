package com.coremasterkb.serving.retrieval;

import com.coremasterkb.serving.domain.QueryPlan;
import com.coremasterkb.serving.domain.RetrievalCandidate;

import java.util.List;

/**
 * Retriever SPI — each implementation fetches candidates from one backend.
 */
public interface Retriever {

    /**
     * Retrieve candidates matching the given plan from the specified snapshots.
     *
     * @param plan        the query plan
     * @param snapshotIds active snapshot IDs to scope the search
     * @return ranked candidates (highest score first)
     */
    List<RetrievalCandidate> retrieve(QueryPlan plan, List<String> snapshotIds);

    /** Identifier used in RetrieverConfig.enabledRetrievers. */
    String name();
}
