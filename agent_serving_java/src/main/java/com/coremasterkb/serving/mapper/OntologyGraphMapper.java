package com.coremasterkb.serving.mapper;

import com.coremasterkb.serving.mapper.result.OntologyGraphRow;
import org.apache.ibatis.annotations.Param;

import java.util.List;

/**
 * Ontology-graph retrieval queries over the {@code ontology_*} tables.
 *
 * <p>Lives in {@code com.coremasterkb.serving.mapper} so it is picked up by the existing
 * {@code @MapperScan} on {@code AgentServingApplication} and shares the domain-routing
 * DataSource (queries hit the request's domain DB via {@code DomainContext}). The ontology
 * tables are co-located with {@code asset_retrieval_units} in the same domain database, so
 * recall completes in a single JOIN without any cross-service/cross-DB call.</p>
 */
public interface OntologyGraphMapper {

    /**
     * Entity linking: resolve query entity names to canonical ontology entity ids.
     *
     * @param domain domain id (also the {@code domain_id} column filter)
     * @param names  normalized (lower-cased, trimmed) query entity names / keywords
     * @return distinct seed entity ids (empty when nothing links)
     */
    List<String> linkEntities(@Param("domain") String domain,
                              @Param("names") List<String> names);

    /**
     * Bounded multi-hop recall: from seed entities, traverse {@code ontology_entity_relations}
     * up to {@code maxHop} hops (cycle-guarded), map hit entities back to evidence segments and
     * then to retrieval units in scope. One row per retrieval unit, aggregated to its shortest
     * hop / best path confidence.
     *
     * @param seedIds     seed entity ids from {@link #linkEntities}
     * @param snapshotIds document snapshots in scope
     * @param maxHop      max traversal depth (>=1)
     * @param minRelConf  minimum edge confidence to traverse (pruning)
     * @param limit       max rows (topK)
     */
    List<OntologyGraphRow> graphRecall(@Param("domain") String domain,
                                       @Param("seedIds") List<String> seedIds,
                                       @Param("snapshotIds") List<String> snapshotIds,
                                       @Param("maxHop") int maxHop,
                                       @Param("minRelConf") double minRelConf,
                                       @Param("limit") int limit);
}
