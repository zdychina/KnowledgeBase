package com.coremasterkb.serving.retrieval;

import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.RetrievalQuery;
import java.util.List;

/**
 * Abstract Retriever interface for retrieval strategies.
 *
 * <p>All retrievers implement the same interface so the search pipeline
 * can swap between BM25, vector, or hybrid without code changes.</p>
 */
public interface Retriever {

    /**
     * Return scored candidates from the index.
     *
     * @param query       structured query with keywords, entities, embedding
     * @param snapshotIds document snapshots in scope
     * @param topK        maximum candidates to return
     * @return scored candidates sorted by descending relevance
     */
    List<RetrievalCandidate> retrieve(RetrievalQuery query, List<String> snapshotIds, int topK);
}
