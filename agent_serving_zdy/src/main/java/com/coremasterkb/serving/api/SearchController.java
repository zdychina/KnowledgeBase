package com.coremasterkb.serving.api;

import com.coremasterkb.serving.application.SearchService;
import com.coremasterkb.serving.domain.ContextPack;
import com.coremasterkb.serving.domain.Issue;
import com.coremasterkb.serving.domain.SearchRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/v1")
public class SearchController {

    private static final Logger log = LoggerFactory.getLogger(SearchController.class);

    private final SearchService searchService;

    public SearchController(SearchService searchService) {
        this.searchService = searchService;
    }

    @PostMapping("/search")
    public ResponseEntity<Map<String, Object>> search(@RequestBody SearchRequest request) {
        long start = System.currentTimeMillis();
        log.info("[search] >>> query=\"{}\", domain={}, channel={}, mode={}, complexityHint={}, debug={}",
                request.query(), request.domain(), request.channel(),
                request.mode(), request.complexityHint(), request.debug());

        ContextPack pack = searchService.search(request);

        long elapsed = System.currentTimeMillis() - start;
        String issueTypes = pack.issues().stream()
                .map(Issue::type).reduce((a, b) -> a + "," + b).orElse("none");
        log.info("[search] <<< items={}, issues=[{}], latency={}ms",
                pack.items().size(), issueTypes, elapsed);

        Map<String, Object> response = new LinkedHashMap<>();
        response.put("query", pack.query());
        response.put("items", pack.items());
        response.put("relations", pack.relations());
        response.put("sources", pack.sources());
        response.put("evidence_groups", pack.evidenceGroups());
        response.put("issues", pack.issues());
        response.put("suggestions", pack.suggestions());

        if (request.debug() && pack.debug() != null) {
            response.put("debug", pack.debug());
        }

        return ResponseEntity.ok(response);
    }
}
