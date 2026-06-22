package com.coremasterkb.serving.operator.config;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.context.annotation.Configuration;

/**
 * Wiring for the pluggable retrieval operator subsystem.
 *
 * <p>Registers operator-specific MyBatis mappers. These use the same (routing) SqlSessionFactory
 * as the existing mappers, so dense retrieval hits the request's domain DB via {@code DomainContext}.
 * The existing {@code @MapperScan("...serving.mapper")} on {@code AgentServingApplication} is left
 * untouched; this adds the operator mapper package without modifying any existing file.</p>
 *
 * <p>Engine components (registry, compiler, executor) and operators are component-scanned
 * ({@code @Component}); only the mapper scan needs explicit declaration here.</p>
 */
@Configuration
@MapperScan(basePackages = {
        "com.coremasterkb.serving.operator.mapper",
        "com.coremasterkb.serving.operator.paradigm.mapper"
})
public class OperatorBeans {
}
