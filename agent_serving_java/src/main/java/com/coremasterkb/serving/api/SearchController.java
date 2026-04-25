package com.coremasterkb.serving.api;

import com.coremasterkb.serving.application.SearchService;
import com.coremasterkb.serving.domain.ContextPack;
import com.coremasterkb.serving.domain.SearchRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/**
 * REST endpoint for agent search queries.
 * POST /api/v1/search
 */
@RestController
@RequestMapping("/api/v1")
public class SearchController {

    private static final Logger log = LoggerFactory.getLogger(SearchController.class);

    private final SearchService searchService;

    public SearchController(SearchService searchService) {
        this.searchService = searchService;
    }

    /**
     * Main search endpoint.
     *
     * Error mappings (handled by GlobalExceptionHandler):
     *   no_active_release        → 503 Service Unavailable
     *   multiple_active_releases → 500 Internal Server Error
     */
    @PostMapping("/search")
    public ResponseEntity<ContextPack> search(@RequestBody SearchRequest request) {
        log.debug("Search request: query='{}', debug={}", request.query(), request.debug());
        ContextPack pack = searchService.search(request);
        return ResponseEntity.ok(pack);
    }
}
