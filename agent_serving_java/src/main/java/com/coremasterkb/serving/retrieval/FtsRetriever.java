package com.coremasterkb.serving.retrieval;

import com.coremasterkb.serving.domain.QueryPlan;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.mapper.AssetRetrievalUnitMapper;
import com.coremasterkb.serving.mapper.result.FtsResultRow;

import java.util.*;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * PostgreSQL full-text search retriever using ts_rank + websearch_to_tsquery.
 * Java-side tokenization filters stopwords before building the FTS query.
 * Install pg_jieba on the DB for proper Chinese tokenization.
 */
public class FtsRetriever implements Retriever {

    private static final String SOURCE_NAME = "fts_bm25";

    private static final Pattern SPLIT_PATTERN =
            Pattern.compile("[\\s,，、？?。.！!；;：:]+");

    private static final Pattern CJK_PATTERN =
            Pattern.compile("[\\u4e00-\\u9fff]");

    private static final Set<String> STOPWORDS_ZH = Set.of(
            "的","了","在","是","和","与","及","或","也","都","这","那","有","没","不","会","能","要",
            "可以","什么","怎么","如何","哪些","为什么","吗","呢","啊","个","一","到","把","被","让",
            "给","从","对","等","请问","帮我","告诉","知道","想","应该","需要"
    );

    private static final Set<String> STOPWORDS_EN = Set.of(
            "a","an","the","is","are","was","were","be","been","do","does","did",
            "has","have","had","and","or","but","not","no","in","on","at","to","of",
            "for","with","from","by","as","what","which","how","why","when","where","who"
    );

    private final AssetRetrievalUnitMapper retrievalUnitMapper;

    public FtsRetriever(AssetRetrievalUnitMapper retrievalUnitMapper) {
        this.retrievalUnitMapper = retrievalUnitMapper;
    }

    @Override
    public String name() {
        return SOURCE_NAME;
    }

    @Override
    public List<RetrievalCandidate> retrieve(QueryPlan plan, List<String> snapshotIds) {
        List<String> keywords = plan.keywords();
        if (keywords == null || keywords.isEmpty()) return Collections.emptyList();
        if (snapshotIds == null || snapshotIds.isEmpty()) return Collections.emptyList();

        List<String> tokens = tokenize(String.join(" ", keywords));
        if (tokens.isEmpty()) return Collections.emptyList();

        // Build websearch_to_tsquery OR expression: "token1 OR token2 OR token3"
        String ftsQuery = tokens.stream()
                .map(t -> t.replace("'", "''")) // escape single quotes
                .collect(Collectors.joining(" OR "));

        int limit = plan.budget().maxItems() * plan.budget().recallMultiplier();

        List<FtsResultRow> rows = retrievalUnitMapper.searchByFts(ftsQuery, snapshotIds, limit);
        return rows.stream().map(this::rowToCandidate).toList();
    }

    private RetrievalCandidate rowToCandidate(FtsResultRow row) {
        Map<String, Object> metadata = new HashMap<>();
        putIfNotNull(metadata, "document_snapshot_id", row.getDocumentSnapshotId());
        putIfNotNull(metadata, "text",                 row.getText());
        putIfNotNull(metadata, "title",                row.getTitle());
        putIfNotNull(metadata, "block_type",           row.getBlockType());
        putIfNotNull(metadata, "semantic_role",        row.getSemanticRole());
        putIfNotNull(metadata, "source_refs_json",     row.getSourceRefsJson());
        putIfNotNull(metadata, "facets_json",          row.getFacetsJson());
        putIfNotNull(metadata, "target_type",          row.getTargetType());
        putIfNotNull(metadata, "target_ref_json",      row.getTargetRefJson());
        putIfNotNull(metadata, "unit_type",            row.getUnitType());
        putIfNotNull(metadata, "source_segment_id",    row.getSourceSegmentId());
        return new RetrievalCandidate(row.getId(), row.getFtsScore(), SOURCE_NAME, metadata);
    }

    private void putIfNotNull(Map<String, Object> map, String key, Object val) {
        if (val != null) map.put(key, val);
    }

    /**
     * Tokenize text: split on punctuation/whitespace, keep tokens of length >= 2
     * or single CJK characters, and filter stopwords.
     */
    public List<String> tokenize(String text) {
        if (text == null || text.isBlank()) return Collections.emptyList();
        String[] parts = SPLIT_PATTERN.split(text.trim());
        List<String> tokens = new ArrayList<>();
        for (String part : parts) {
            if (part.isEmpty()) continue;
            if (part.length() >= 2 || CJK_PATTERN.matcher(part).matches()) {
                String lower = part.toLowerCase();
                if (!STOPWORDS_ZH.contains(part) && !STOPWORDS_EN.contains(lower)) {
                    tokens.add(part);
                }
            }
        }
        return tokens;
    }
}
