package com.coremasterkb.serving.operator.operators.retrieve;

import com.coremasterkb.serving.domain.ActiveScope;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.ScoreChain;
import com.coremasterkb.serving.mapper.result.ExpandedSegmentRow;
import com.coremasterkb.serving.mapper.result.SegmentWithMetaRow;
import com.coremasterkb.serving.operator.core.*;
import com.coremasterkb.serving.retrieval.GraphExpander;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * {@code graph_expand} — BFS expansion over segment relations from seed candidates. Reuses the
 * existing {@link GraphExpander}. Seed segment ids are taken from each candidate's
 * {@code source_segment_id} (or {@code source_refs_json.raw_segment_ids}); expanded segments are
 * returned as candidates keyed by segment id, source {@code graph_expand}, scored by BFS distance.
 *
 * <p>Note: these candidates are segment-based (not retrieval-unit-based), suitable for collection
 * or as supplementary context; they intentionally surface graph neighbours of the seeds.</p>
 */
@Component
public class GraphExpandOperator implements Operator {

    private static final String SOURCE = "graph_expand";
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static final String PARAM_SCHEMA = """
            {"type":"object","properties":{
              "maxDepth":{"type":"integer","minimum":1,"maximum":5,"default":2,"title":"扩展深度"},
              "maxResults":{"type":"integer","minimum":1,"maximum":50,"default":10,"title":"最大扩展数"},
              "relationTypes":{"type":"array","items":{"type":"string"},"title":"关系类型(留空=全部)"}
            }}""";

    private final GraphExpander graphExpander;

    public GraphExpandOperator(GraphExpander graphExpander) {
        this.graphExpander = graphExpander;
    }

    @Override
    public OperatorDef definition() {
        return new OperatorDef(
                "graph_expand", "retrieve", "图扩展",
                "从种子候选沿段落关系图 BFS 扩展邻居段落",
                List.of(
                        SlotDecl.required("seeds", SlotType.CANDIDATE_LIST, "种子候选"),
                        SlotDecl.required("scope", SlotType.SCOPE, "检索范围(snapshotIds)")),
                List.of(SlotDecl.required("candidates", SlotType.CANDIDATE_LIST, "扩展候选")),
                PARAM_SCHEMA,
                ErrorPolicy.SKIP_WITH_EMPTY);
    }

    @Override
    public SlotValues execute(SlotValues inputs, Params params, ExecContext ctx) {
        List<RetrievalCandidate> seeds = inputs.getCandidates("seeds");
        ActiveScope scope = inputs.getScope("scope");
        if (seeds.isEmpty() || scope == null || scope.snapshotIds().isEmpty()) {
            return SlotValues.of("candidates", List.of());
        }

        List<String> seedSegIds = collectSeedSegmentIds(seeds);
        if (seedSegIds.isEmpty()) {
            return SlotValues.of("candidates", List.of());
        }

        int maxDepth = params.getInt("maxDepth", 2);
        int maxResults = params.getInt("maxResults", 10);
        List<String> relationTypes = params.getStringList("relationTypes");

        List<ExpandedSegmentRow> rows = graphExpander.expand(
                seedSegIds, maxDepth, relationTypes.isEmpty() ? null : relationTypes,
                maxResults, scope.snapshotIds());

        List<RetrievalCandidate> candidates = new ArrayList<>(rows.size());
        for (ExpandedSegmentRow row : rows) {
            candidates.add(toCandidate(row));
        }
        return SlotValues.of("candidates", candidates);
    }

    private static List<String> collectSeedSegmentIds(List<RetrievalCandidate> seeds) {
        Set<String> ids = new LinkedHashSet<>();
        for (RetrievalCandidate c : seeds) {
            Object segId = c.metadata().get("source_segment_id");
            if (segId instanceof String s && !s.isBlank()) {
                ids.add(s);
                continue;
            }
            Object refs = c.metadata().get("source_refs_json");
            if (refs instanceof String json && !json.isBlank()) {
                ids.addAll(parseRawSegmentIds(json));
            }
        }
        return new ArrayList<>(ids);
    }

    @SuppressWarnings("unchecked")
    private static List<String> parseRawSegmentIds(String json) {
        try {
            Map<String, Object> m = MAPPER.readValue(json, new TypeReference<Map<String, Object>>() {});
            Object raw = m.get("raw_segment_ids");
            if (raw instanceof List<?> list) {
                List<String> out = new ArrayList<>();
                for (Object o : list) {
                    if (o != null) out.add(String.valueOf(o));
                }
                return out;
            }
        } catch (Exception ignore) {
            // not parseable — skip
        }
        return List.of();
    }

    private static RetrievalCandidate toCandidate(ExpandedSegmentRow row) {
        SegmentWithMetaRow seg = row.segment();
        double score = 1.0 / (1 + Math.max(0, row.expansionDistance()));
        Map<String, Object> meta = new LinkedHashMap<>();
        putIfNotNull(meta, "text", seg.getRawText());
        putIfNotNull(meta, "title", seg.getSnapshotTitle());
        putIfNotNull(meta, "block_type", seg.getBlockType());
        putIfNotNull(meta, "semantic_role", seg.getSemanticRole());
        putIfNotNull(meta, "document_snapshot_id", seg.getDocumentSnapshotId());
        putIfNotNull(meta, "source_segment_id", seg.getId());
        putIfNotNull(meta, "relation_type", row.relationType());
        meta.put("expansion_distance", row.expansionDistance());
        return new RetrievalCandidate(
                seg.getId(), score, SOURCE, meta,
                new ScoreChain(score, 0.0, 0.0, List.of(SOURCE)));
    }

    private static void putIfNotNull(Map<String, Object> map, String key, Object val) {
        if (val != null) map.put(key, val);
    }
}
