package com.coremasterkb.serving.retrieval;

import com.coremasterkb.serving.domain.EntityRef;
import com.coremasterkb.serving.domain.QueryUnderstanding;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.ScoreChain;
import com.coremasterkb.serving.mapper.OntologyGraphMapper;
import com.coremasterkb.serving.mapper.result.OntologyGraphRow;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Ontology-graph recall: link query entities to canonical ontology entities, traverse the
 * entity relation graph (bounded, cycle-guarded), map hits back through evidence to retrieval
 * units, and score by hop-distance decay × path confidence.
 *
 * <p>Not an implementation of {@link Retriever} on purpose — it needs {@code domain} and graph
 * options that the fixed {@code Retriever#retrieve} signature can't carry (same as
 * {@code GraphExpander}). It is wrapped by {@code EntityGraphOperator}. Marked {@code @Component}
 * so it self-registers without touching {@code ServingBeans}; the injected mapper rides the
 * request's domain-routing DataSource.</p>
 */
@Component
public class EntityGraphRetriever {

    /** Tunable knobs supplied by the operator's node params. */
    public record Options(int topK, int maxHop, double minRelConf, double decay) {}

    private static final String SOURCE = "entity_graph";
    /** Base score for a hop-0 exact-confidence evidence unit (below entity_exact's 0.95). */
    private static final double BASE = 0.85;
    /** Small boost for entity_card units (built specifically for strong entities). */
    private static final double ENTITY_CARD_BOOST = 1.1;

    private final OntologyGraphMapper mapper;

    public EntityGraphRetriever(OntologyGraphMapper mapper) {
        this.mapper = mapper;
    }

    /**
     * @param u           query understanding (entities + keywords)
     * @param snapshotIds document snapshots in scope
     * @param domain      domain id (drives {@code domain_id} filter; DB is already domain-routed)
     * @param opts        topK / maxHop / minRelConf / decay
     * @return scored candidates (empty when no ontology, no entity link, or no evidence in scope)
     */
    public List<RetrievalCandidate> retrieve(QueryUnderstanding u, List<String> snapshotIds,
                                             String domain, Options opts) {
        if (u == null || snapshotIds == null || snapshotIds.isEmpty()
                || domain == null || domain.isBlank()) {
            return List.of();
        }
        List<String> names = collectNames(u);
        if (names.isEmpty()) {
            return List.of();
        }
        List<String> seedIds = mapper.linkEntities(domain, names);
        if (seedIds.isEmpty()) {
            return List.of();   // no_entity_link — operator returns empty candidates
        }
        List<OntologyGraphRow> rows = mapper.graphRecall(
                domain, seedIds, snapshotIds,
                Math.max(1, opts.maxHop()), opts.minRelConf(), Math.max(1, opts.topK()));

        List<RetrievalCandidate> out = new ArrayList<>(rows.size());
        for (OntologyGraphRow row : rows) {
            out.add(toCandidate(row, opts.decay()));
        }
        return out;
    }

    /** Query entity names (name + normalizedName), lower-cased/trimmed; keywords as fallback. */
    private static List<String> collectNames(QueryUnderstanding u) {
        Set<String> names = new LinkedHashSet<>();
        for (EntityRef ref : u.entities()) {
            addName(names, ref.name());
            addName(names, ref.normalizedName());
        }
        if (names.isEmpty()) {
            for (String kw : u.keywords()) {
                if (kw != null && kw.length() >= 2) {
                    addName(names, kw);
                }
            }
        }
        return new ArrayList<>(names);
    }

    private static void addName(Set<String> set, String s) {
        if (s != null && !s.isBlank()) {
            set.add(s.trim().toLowerCase());
        }
    }

    private RetrievalCandidate toCandidate(OntologyGraphRow row, double decay) {
        double conf = row.getConf() <= 0.0 ? 0.01 : Math.min(1.0, row.getConf());
        double d = (decay <= 0.0 || decay > 1.0) ? 0.6 : decay;
        double boost = "entity_card".equals(row.getUnitType()) ? ENTITY_CARD_BOOST : 1.0;
        double score = BASE * Math.pow(d, Math.max(0, row.getHop())) * conf * boost;

        Map<String, Object> meta = new LinkedHashMap<>();
        putIfNotNull(meta, "text", row.getText());
        putIfNotNull(meta, "title", row.getTitle());
        putIfNotNull(meta, "document_snapshot_id", row.getDocumentSnapshotId());
        putIfNotNull(meta, "block_type", row.getBlockType());
        putIfNotNull(meta, "semantic_role", row.getSemanticRole());
        putIfNotNull(meta, "unit_type", row.getUnitType());
        putIfNotNull(meta, "source_segment_id", row.getSourceSegmentId());
        meta.put("graph_hop", row.getHop());
        meta.put("graph_conf", row.getConf());

        return new RetrievalCandidate(
                row.getId(), score, SOURCE, meta,
                new ScoreChain(score, 0.0, 0.0, List.of(SOURCE)));
    }

    private static void putIfNotNull(Map<String, Object> map, String key, Object val) {
        if (val != null) {
            map.put(key, val);
        }
    }
}
