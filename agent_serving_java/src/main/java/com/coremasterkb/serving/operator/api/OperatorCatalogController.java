package com.coremasterkb.serving.operator.api;

import com.coremasterkb.serving.operator.core.OperatorDef;
import com.coremasterkb.serving.operator.registry.OperatorRegistry;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * Operator catalog endpoint — the frontend canvas renders the operator palette and per-operator
 * param forms from this. Each {@link OperatorDef} carries slots + a JSON Schema for params.
 */
@RestController
@RequestMapping("/api/v1/operator")
public class OperatorCatalogController {

    private final OperatorRegistry registry;

    public OperatorCatalogController(OperatorRegistry registry) {
        this.registry = registry;
    }

    @GetMapping("/catalog")
    public Map<String, List<OperatorDef>> catalog() {
        return Map.of("operators", registry.allDefinitions());
    }
}
