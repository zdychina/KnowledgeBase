package com.coremasterkb.serving.retrieval;

import com.coremasterkb.serving.domain.RetrievalCandidate;
import com.coremasterkb.serving.domain.RetrievalQuery;
import com.coremasterkb.serving.domain.ScoreChain;
import com.coremasterkb.serving.mapper.AssetRetrievalUnitMapper;
import com.coremasterkb.serving.mapper.result.FtsResultRow;
import com.huaban.analysis.jieba.JiebaSegmenter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.BadSqlGrammarException;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * PostgreSQL FTS retriever with three-level degradation.
 *
 * <p>Level 1: tsvector search (websearch_to_tsquery) with scope filter<br>
 * Level 2: pg_trgm trigram fuzzy (if level 1 fails)<br>
 * Level 3: LIKE fallback (if level 2 fails)</p>
 *
 * <p>Scope filter pushdown uses JSONB parameterized queries.
 * Auto-retry without scope on failure.</p>
 */
public class FtsRetriever implements Retriever {

    private static final Logger log = LoggerFactory.getLogger(FtsRetriever.class);
    private static final String SOURCE_TSVECTOR = "lexical_bm25";
    private static final String SOURCE_TRIGRAM = "trigram_fallback";
    private static final String SOURCE_LIKE = "like_fallback";

    private static final ThreadLocal<JiebaSegmenter> SEGMENTER_TL =
            ThreadLocal.withInitial(JiebaSegmenter::new);
    private static final Pattern CJK_PATTERN = Pattern.compile("[\\u4e00-\\u9fff]");

    private static final Set<String> STOPWORDS_ZH = loadStopwords("fts/stopwords_zh.txt");
    private static final Set<String> STOPWORDS_EN = loadStopwords("fts/stopwords_en.txt");

    private final AssetRetrievalUnitMapper retrievalUnitMapper;

    public FtsRetriever(AssetRetrievalUnitMapper retrievalUnitMapper) {
        this.retrievalUnitMapper = retrievalUnitMapper;
    }

    // -------------------------------------------------------------------------
    // Retriever interface
    // -------------------------------------------------------------------------

    @Override
    public List<RetrievalCandidate> retrieve(RetrievalQuery query, List<String> snapshotIds, int topK) {
        if (snapshotIds == null || snapshotIds.isEmpty()) {
            return Collections.emptyList();
        }

        List<String> searchTerms = collectSearchTerms(query);
        if (searchTerms.isEmpty()) {
            return Collections.emptyList();
        }

        // Tokenize with jieba (consistent with Mining's tokenize_for_search)
        String rawQuery = String.join(" ", searchTerms);
        List<String> tokens = tokenize(rawQuery);
        if (tokens.isEmpty()) {
            return Collections.emptyList();
        }

        // Build websearch_to_tsquery OR expression: "token1 OR token2 OR token3"
        String ftsQuery = tokens.stream()
                .map(t -> t.replace("'", "''"))
                .collect(Collectors.joining(" OR "));

        int recallLimit = topK * 5;

        // Level 1: tsvector full-text search
        List<RetrievalCandidate> candidates = tryTsvector(
                ftsQuery, snapshotIds, recallLimit, query.scope());
        if (!candidates.isEmpty()) {
            return candidates;
        }

        // Level 2: pg_trgm trigram similarity fallback
        log.debug("tsvector returned no results, falling back to trigram for query={}", ftsQuery);
        candidates = tryTrigram(rawQuery, tokens, snapshotIds, recallLimit, query.scope());
        if (!candidates.isEmpty()) {
            return candidates;
        }

        // Level 3: LIKE fallback
        log.debug("trigram returned no results, falling back to LIKE for query={}", ftsQuery);
        return tryLike(tokens, snapshotIds, recallLimit, query.scope());
    }

    // -------------------------------------------------------------------------
    // Level 1: tsvector
    // -------------------------------------------------------------------------

    private List<RetrievalCandidate> tryTsvector(
            String ftsQuery, List<String> snapshotIds, int limit, Map<String, Object> scope) {

        // With scope
        List<String> scopeJsonParams = buildScopeJsonParams(scope);
        List<FtsResultRow> rows = retrievalUnitMapper.searchByFtsWithScope(
                ftsQuery, snapshotIds, scopeJsonParams, limit);

        // Retry without scope if scope eliminated all results
        if (rows.isEmpty() && !scopeJsonParams.isEmpty()) {
            log.info("Scope filter eliminated all BM25 results, retrying without scope");
            rows = retrievalUnitMapper.searchByFts(ftsQuery, snapshotIds, limit);
        }

        return rows.stream()
                .map(row -> toCandidate(row, SOURCE_TSVECTOR))
                .toList();
    }

    // -------------------------------------------------------------------------
    // Level 2: trigram
    // -------------------------------------------------------------------------

    private List<RetrievalCandidate> tryTrigram(
            String rawQuery, List<String> tokens,
            List<String> snapshotIds, int limit, Map<String, Object> scope) {

        String queryText = String.join(" ", tokens);
        List<String> scopeJsonParams = buildScopeJsonParams(scope);

        try {
            List<FtsResultRow> rows = retrievalUnitMapper.searchByTrigramWithScope(
                    queryText, snapshotIds, scopeJsonParams, limit);

            if (rows.isEmpty() && !scopeJsonParams.isEmpty()) {
                log.info("Scope filter eliminated all trigram results, retrying without scope");
                rows = retrievalUnitMapper.searchByTrigram(queryText, snapshotIds, limit);
            }

            return rows.stream()
                    .map(row -> toCandidate(row, SOURCE_TRIGRAM))
                    .toList();
        } catch (BadSqlGrammarException e) {
            // pg_trgm extension not installed — skip this level and fall through to LIKE
            log.warn("pg_trgm not available, skipping trigram fallback: {}", e.getMostSpecificCause().getMessage());
            return Collections.emptyList();
        }
    }

    // -------------------------------------------------------------------------
    // Level 3: LIKE fallback
    // -------------------------------------------------------------------------

    private List<RetrievalCandidate> tryLike(
            List<String> tokens, List<String> snapshotIds,
            int limit, Map<String, Object> scope) {

        List<String> scopeJsonParams = buildScopeJsonParams(scope);
        List<String> likeTerms = tokens.stream()
                .map(t -> "%" + t + "%")
                .toList();

        List<FtsResultRow> rows = retrievalUnitMapper.searchByLikeWithScope(
                likeTerms, snapshotIds, scopeJsonParams, limit);

        if (rows.isEmpty() && !scopeJsonParams.isEmpty()) {
            log.info("Scope filter eliminated all LIKE results, retrying without scope");
            rows = retrievalUnitMapper.searchByLike(likeTerms, snapshotIds, limit);
        }

        // Score by keyword hit ratio
        List<String> tokenLower = tokens.stream()
                .map(String::toLowerCase)
                .toList();

        return rows.stream()
                .map(row -> {
                    String text = row.getText() != null ? row.getText().toLowerCase() : "";
                    long hitCount = tokenLower.stream().filter(text::contains).count();
                    double score = tokenLower.isEmpty() ? 0.0 : (double) hitCount / tokenLower.size();
                    return toCandidateWithScore(row, score, SOURCE_LIKE);
                })
                .toList();
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    private List<String> collectSearchTerms(RetrievalQuery query) {
        List<String> terms = new ArrayList<>(query.keywords());
        for (String sq : query.subQueries()) {
            if (sq != null && !sq.isBlank()) {
                terms.addAll(List.of(sq.split("\\s+")));
            }
        }
        if (terms.isEmpty() && query.originalQuery() != null && !query.originalQuery().isBlank()) {
            terms.addAll(List.of(query.originalQuery().split("\\s+")));
        }
        return terms;
    }

    /**
     * Tokenize text using jieba segmentation (matches write-side Python jieba),
     * then filter stopwords and short tokens.
     */
    public List<String> tokenize(String text) {
        if (text == null || text.isBlank()) {
            return Collections.emptyList();
        }
        List<String> raw = SEGMENTER_TL.get().sentenceProcess(text).stream()
                .map(String::trim)
                .filter(t -> !t.isBlank())
                .toList();
        List<String> filtered = raw.stream()
                .filter(t -> t.length() >= 2 || CJK_PATTERN.matcher(t).matches())
                .filter(t -> !STOPWORDS_ZH.contains(t) && !STOPWORDS_EN.contains(t.toLowerCase()))
                .collect(Collectors.toList());
        return filtered.isEmpty() ? raw : filtered;
    }

    /**
     * Build scope JSON parameters for parameterized JSONB @> containment queries.
     * Each scope entry {key: [values]} becomes a JSON string like {"key":["v1","v2"]}.
     */
    static List<String> buildScopeJsonParams(Map<String, Object> scope) {
        if (scope == null || scope.isEmpty()) {
            return List.of();
        }
        List<String> params = new ArrayList<>();
        for (Map.Entry<String, Object> entry : scope.entrySet()) {
            if (entry.getValue() instanceof List<?> values && !values.isEmpty()) {
                StringBuilder sb = new StringBuilder();
                sb.append("{\"").append(entry.getKey()).append("\":[");
                for (int i = 0; i < values.size(); i++) {
                    if (i > 0) sb.append(',');
                    sb.append('"').append(escapeJson(values.get(i).toString())).append('"');
                }
                sb.append("]}");
                params.add(sb.toString());
            }
        }
        return params;
    }

    private static String escapeJson(String value) {
        return value.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    private RetrievalCandidate toCandidate(FtsResultRow row, String source) {
        return toCandidateWithScore(row, row.getFtsScore(), source);
    }

    private RetrievalCandidate toCandidateWithScore(FtsResultRow row, double score, String source) {
        Map<String, Object> metadata = new HashMap<>();
        putIfNotNull(metadata, "document_snapshot_id", row.getDocumentSnapshotId());
        putIfNotNull(metadata, "text", row.getText());
        putIfNotNull(metadata, "title", row.getTitle());
        putIfNotNull(metadata, "block_type", row.getBlockType());
        putIfNotNull(metadata, "semantic_role", row.getSemanticRole());
        putIfNotNull(metadata, "source_refs_json", row.getSourceRefsJson());
        putIfNotNull(metadata, "facets_json", row.getFacetsJson());
        putIfNotNull(metadata, "target_type", row.getTargetType());
        putIfNotNull(metadata, "target_ref_json", row.getTargetRefJson());
        putIfNotNull(metadata, "unit_type", row.getUnitType());
        putIfNotNull(metadata, "source_segment_id", row.getSourceSegmentId());

        return new RetrievalCandidate(
                row.getId(),
                score,
                source,
                metadata,
                new ScoreChain(score, 0.0, 0.0, List.of(source))
        );
    }

    private void putIfNotNull(Map<String, Object> map, String key, Object val) {
        if (val != null) {
            map.put(key, val);
        }
    }

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
}
