package com.coremasterkb.serving.api;

import com.coremasterkb.serving.domainpack.ConfigReloadService;
import com.coremasterkb.serving.domainpack.DomainRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Admin endpoints for runtime config hot-reload. The kb-ui "配置热重载" button reaches
 * {@code reload-config} via main_control's fan-out ({@code POST /api/v1/admin/reload-serving}).
 */
@RestController
@RequestMapping("/api/v1/admin")
public class AdminController {

    private static final Logger log = LoggerFactory.getLogger(AdminController.class);

    private final ConfigReloadService configReloadService;
    private final DomainRegistry domainRegistry;

    public AdminController(ConfigReloadService configReloadService, DomainRegistry domainRegistry) {
        this.configReloadService = configReloadService;
        this.domainRegistry = domainRegistry;
    }

    @PostMapping("/reload-config")
    public ResponseEntity<Map<String, Object>> reloadConfig() {
        log.info("[admin] config reload requested");
        int domains = configReloadService.reload();
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("ok", true);
        body.put("domains", domainRegistry.knownDomains());
        body.put("count", domains);
        log.info("[admin] config reload done: {} domain(s)", domains);
        return ResponseEntity.ok(body);
    }

    @GetMapping("/config-status")
    public ResponseEntity<Map<String, Object>> configStatus() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("loaded", domainRegistry.isLoaded());
        body.put("domains", domainRegistry.knownDomains());
        return ResponseEntity.ok(body);
    }
}
