package com.coremasterkb.serving.retrieval;

import com.huaban.analysis.jieba.JiebaSegmenter;
import com.coremasterkb.serving.domain.QueryPlan;
import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.mapper.AssetRetrievalUnitMapper;
import com.coremasterkb.serving.mapper.result.FtsResultRow;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * PostgreSQL full-text search retriever using ts_rank + websearch_to_tsquery.
 * Query-side tokenization uses jieba (Java port) to match write-side Python jieba segmentation.
 * Stopwords are loaded from classpath: fts/stopwords_zh.txt and fts/stopwords_en.txt.
 */
public class FtsRetriever implements Retriever {

    private static final String SOURCE_NAME = "fts_bm25";

    private static final JiebaSegmenter SEGMENTER = new JiebaSegmenter();

    private static final Pattern CJK_PATTERN =
            Pattern.compile("[\\u4e00-\\u9fff]");

    private static final Set<String> STOPWORDS_ZH = loadStopwords("fts/stopwords_zh.txt");
    private static final Set<String> STOPWORDS_EN = loadStopwords("fts/stopwords_en.txt");

    private static Set<String> loadStopwords(String classpathResource) {
        try (InputStream is = FtsRetriever.class.getClassLoader().getResourceAsStream(classpathResource)) {
            if (is == null) return Set.of();
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8))) {
                Set<String> words = new HashSet<>();
                String line;
                while ((line = reader.readLine()) != null) {
                    line = line.strip();
                    if (!line.isEmpty()) words.add(line);
                }
                return Collections.unmodifiableSet(words);
            }
        } catch (IOException e) {
            return Set.of();
        }
    }

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
     * Tokenize text using jieba segmentation (matches write-side Python jieba),
     * then filter stopwords and short tokens.
     * Falls back to raw jieba output when all tokens are filtered out (e.g. "不可以").
     */
    public List<String> tokenize(String text) {
        if (text == null || text.isBlank()) return Collections.emptyList();
        List<String> raw = SEGMENTER.sentenceProcess(text).stream()
                .map(String::trim)
                .filter(t -> !t.isBlank())
                .toList();
        List<String> filtered = raw.stream()
                .filter(t -> t.length() >= 2 || CJK_PATTERN.matcher(t).matches())
                .filter(t -> !STOPWORDS_ZH.contains(t) && !STOPWORDS_EN.contains(t.toLowerCase()))
                .collect(Collectors.toList());
        return filtered.isEmpty() ? raw : filtered;
    }
}
