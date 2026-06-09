package com.coremasterkb.serving.mapper;

import com.coremasterkb.serving.mapper.result.FtsResultRow;
import org.apache.ibatis.annotations.Param;

import java.util.List;

public interface AssetRetrievalUnitMapper {

    // ----- Level 1: tsvector full-text search -----

    List<FtsResultRow> searchByFts(
            @Param("ftsQuery") String ftsQuery,
            @Param("snapshotIds") List<String> snapshotIds,
            @Param("limit") int limit);

    /**
     * tsvector search with scope filter (facets_json JSONB containment) and an optional
     * section hard filter. When {@code sectionPrefixes} is non-empty, only units whose source
     * raw segment's top-level section title is in the set are returned (PageIndex-style narrowing).
     */
    List<FtsResultRow> searchByFtsWithScope(
            @Param("ftsQuery") String ftsQuery,
            @Param("snapshotIds") List<String> snapshotIds,
            @Param("scopeJsonParams") List<String> scopeJsonParams,
            @Param("sectionPrefixes") List<String> sectionPrefixes,
            @Param("limit") int limit);

    // ----- Level 2: pg_trgm trigram similarity -----

    /** Trigram similarity fallback without scope. */
    List<FtsResultRow> searchByTrigram(
            @Param("queryText") String queryText,
            @Param("snapshotIds") List<String> snapshotIds,
            @Param("limit") int limit);

    /** Trigram similarity with scope filter. */
    List<FtsResultRow> searchByTrigramWithScope(
            @Param("queryText") String queryText,
            @Param("snapshotIds") List<String> snapshotIds,
            @Param("scopeJsonParams") List<String> scopeJsonParams,
            @Param("limit") int limit);

    // ----- Level 3: LIKE fallback -----

    /** LIKE fallback without scope. */
    List<FtsResultRow> searchByLike(
            @Param("likeTerms") List<String> likeTerms,
            @Param("snapshotIds") List<String> snapshotIds,
            @Param("limit") int limit);

    /** LIKE fallback with scope filter. */
    List<FtsResultRow> searchByLikeWithScope(
            @Param("likeTerms") List<String> likeTerms,
            @Param("snapshotIds") List<String> snapshotIds,
            @Param("scopeJsonParams") List<String> scopeJsonParams,
            @Param("limit") int limit);

    // ----- Entity exact -----

    /**
     * Entity-exact search: returns units whose entity_refs_json contains
     * any element with a "name" field matching one of the given entityNames.
     * When {@code sectionPrefixes} is non-empty, additionally restricts to units whose source
     * raw segment's top-level section title is in the set (section hard filter).
     */
    List<FtsResultRow> searchByEntityExact(
            @Param("entityNames") List<String> entityNames,
            @Param("snapshotIds") List<String> snapshotIds,
            @Param("sectionPrefixes") List<String> sectionPrefixes,
            @Param("limit") int limit);
}
