# ── Stage 1: build ───────────────────────────────────────────────────────────
FROM maven:3.9.6-eclipse-temurin-21 AS builder

WORKDIR /build

# Resolve dependencies first so this layer is cached separately from source changes
COPY pom.xml .
RUN mvn dependency:go-offline -q

COPY src ./src
RUN mvn package -Dmaven.test.skip=true -q

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM eclipse-temurin:21-jre-jammy AS runtime

RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

COPY --from=builder /build/target/agent-serving-*.jar app.jar

# Mount point for domain_registry.yaml and scenario_packs/ (injected at runtime)
RUN mkdir -p /app/config/scenario_packs && chown -R appuser:appuser /app

USER appuser

ENV DOMAIN_REGISTRY_PATH=/app/config/domain_registry.yaml \
    SCENARIO_PACKS_DIR=/app/config/scenario_packs

EXPOSE 8082

ENTRYPOINT ["java", "-jar", "/app/app.jar"]
