package com.coremasterkb.serving.operator.registry;

import com.coremasterkb.serving.operator.core.Operator;
import com.coremasterkb.serving.operator.core.OperatorDef;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Operator catalog: indexes every {@link Operator} Spring bean by its {@code definition().type()}.
 *
 * <p>Static registration — operators are discovered at startup via constructor injection of all
 * {@code Operator} beans. A duplicate type id fails fast at startup (configuration error).</p>
 */
@Component
public class OperatorRegistry {

    private static final Logger log = LoggerFactory.getLogger(OperatorRegistry.class);

    private final Map<String, Operator> operatorsByType = new LinkedHashMap<>();
    private final Map<String, OperatorDef> defsByType = new LinkedHashMap<>();

    public OperatorRegistry(List<Operator> operators) {
        for (Operator op : operators) {
            OperatorDef def = op.definition();
            String type = def.type();
            if (operatorsByType.containsKey(type)) {
                throw new IllegalStateException("Duplicate operator type registered: '" + type + "' ("
                        + op.getClass().getName() + " vs " + operatorsByType.get(type).getClass().getName() + ")");
            }
            operatorsByType.put(type, op);
            defsByType.put(type, def);
        }
        log.info("OperatorRegistry initialized with {} operators: {}",
                operatorsByType.size(), operatorsByType.keySet());
    }

    public boolean contains(String type) {
        return operatorsByType.containsKey(type);
    }

    public Operator get(String type) {
        return operatorsByType.get(type);
    }

    public OperatorDef def(String type) {
        return defsByType.get(type);
    }

    /** All operator definitions, for the {@code /operator/catalog} endpoint. */
    public List<OperatorDef> allDefinitions() {
        return List.copyOf(defsByType.values());
    }
}
