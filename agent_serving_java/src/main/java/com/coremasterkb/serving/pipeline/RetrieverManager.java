package com.coremasterkb.serving.pipeline;

import com.coremasterkb.serving.domain.QueryPlan;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.retrieval.Retriever;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

/**
 * Manages multiple Retriever instances and invokes the ones enabled in QueryPlan.
 */
public class RetrieverManager {

    private final Map<String, Retriever> retrievers;

    public RetrieverManager(List<Retriever> retrievers) {
        this.retrievers = retrievers.stream()
                .collect(Collectors.toMap(Retriever::name, Function.identity()));
    }

    /**
     * Call each enabled retriever and collect all candidates.
     *
     * @param plan        query plan (contains retriever_config.enabled_retrievers)
     * @param snapshotIds active snapshot scope
     * @return combined candidates from all enabled retrievers
     */
    public List<RetrievalCandidate> retrieve(QueryPlan plan, List<String> snapshotIds) {
        List<String> enabled = plan.retrieverConfig().enabledRetrievers();
        if (enabled == null || enabled.isEmpty()) {
            return Collections.emptyList();
        }

        List<RetrievalCandidate> all = new ArrayList<>();
        for (String name : enabled) {
            Retriever r = retrievers.get(name);
            if (r != null) {
                List<RetrievalCandidate> results = r.retrieve(plan, snapshotIds);
                all.addAll(results);
            }
        }
        return all;
    }
}
