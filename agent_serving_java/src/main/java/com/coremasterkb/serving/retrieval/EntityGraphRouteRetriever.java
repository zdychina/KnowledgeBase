package com.coremasterkb.serving.retrieval;

import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.RetrievalQuery;
import com.coremasterkb.serving.domainpack.DomainContext;

import java.util.List;

/**
 * Adapts {@link EntityGraphRetriever} to the fixed {@link Retriever} contract so ontology-graph
 * recall can run as a route in the legacy {@code /api/v1/search} orchestrator (alongside
 * {@code lexical_bm25} / {@code dense_vector} / {@code entity_exact}).
 *
 * <p>The {@link Retriever} signature carries neither {@code domain} nor graph options, so:
 * <ul>
 *   <li>{@code domain} is read from {@link DomainContext#get()} — the same source the
 *       domain-routing DataSource uses on the retrieval thread; blank means no domain in scope,
 *       so we skip (empty candidates);</li>
 *   <li>graph knobs ({@code maxHop} / {@code minRelConf} / {@code decay}) use fixed defaults
 *       matching the operator's schema defaults ({@code EntityGraphOperator}); {@code topK} comes
 *       from the route's {@code top_k}.</li>
 * </ul>
 *
 * <p>Names come straight from {@link RetrievalQuery#entities()} (keywords as fallback), reusing
 * {@link EntityGraphRetriever#retrieve(List, List, List, String, EntityGraphRetriever.Options)}.
 * Wired in {@code ServingBeans}; the operator-system path is unaffected.</p>
 */
public class EntityGraphRouteRetriever implements Retriever {

    /** Fixed graph knobs — mirror EntityGraphOperator's paramSchema defaults. */
    private static final int DEFAULT_MAX_HOP = 2;
    private static final double DEFAULT_MIN_REL_CONF = 0.5;
    private static final double DEFAULT_DECAY = 0.6;

    private final EntityGraphRetriever delegate;

    public EntityGraphRouteRetriever(EntityGraphRetriever delegate) {
        this.delegate = delegate;
    }

    @Override
    public List<RetrievalCandidate> retrieve(RetrievalQuery query, List<String> snapshotIds, int topK) {
        String domain = DomainContext.get();
        if (domain == null || domain.isBlank()) {
            return List.of();
        }
        var opts = new EntityGraphRetriever.Options(
                topK, DEFAULT_MAX_HOP, DEFAULT_MIN_REL_CONF, DEFAULT_DECAY);
        return delegate.retrieve(query.entities(), query.keywords(), snapshotIds, domain, opts);
    }
}
