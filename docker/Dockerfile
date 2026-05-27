# ── CoreMasterKB All-in-One ──────────────────────────────────────────
# 多阶段构建：Stage 1-2 编译，Stage 3 只留运行时

# ═══════════════════════════════════════════════════════════════
# Stage 1: 构建 Java (Maven 用完即丢)
# ═══════════════════════════════════════════════════════════════
FROM eclipse-temurin:21-jdk AS build-java
RUN apt-get update && apt-get install -y curl \
    && curl -fsSL https://archive.apache.org/dist/maven/maven-3/3.9.9/binaries/apache-maven-3.9.9-bin.tar.gz \
    | tar xz -C /opt && ln -s /opt/apache-maven-3.9.9/bin/mvn /usr/bin/mvn \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY agent_serving_java/pom.xml .
RUN mvn dependency:go-offline -B -q
COPY agent_serving_java/src ./src
RUN mvn package -DskipTests -B -q

# ═══════════════════════════════════════════════════════════════
# Stage 2: 构建前端 (Node 用完即丢)
# ═══════════════════════════════════════════════════════════════
FROM node:20-alpine AS build-ui
WORKDIR /build
COPY kb-ui/package.json kb-ui/package-lock.json* kb-ui/pnpm-lock.yaml* kb-ui/yarn.lock* ./
RUN npm ci --silent 2>/dev/null || npm install --silent
COPY kb-ui/ .
RUN npm run build

# ═══════════════════════════════════════════════════════════════
# Stage 3: 运行时镜像 (只保留运行必需的)
# ═══════════════════════════════════════════════════════════════
FROM python:3.11-slim

# ── 换国内 Debian 源加速 ──
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources

# ── 运行时系统依赖 ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl libpq-dev supervisor nginx \
    openjdk-21-jre-headless \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python 依赖（仅运行时，不含 dev） ──
COPY pyproject.toml ./
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    "fastapi>=0.110" \
    "uvicorn[standard]>=0.29" \
    "pydantic>=2.7" \
    "pydantic-settings>=2.3" \
    "aiosqlite>=0.20" \
    "PyYAML>=6.0" \
    "markdown-it-py>=3.0" \
    "jinja2>=3.1" \
    "jsonschema>=4.21" \
    "httpx>=0.27" \
    "psycopg[binary,pool]>=3.1" \
    "fastmcp>=2.0"

# ── 从构建阶段复制产物 ──
COPY --from=build-java /build/target/*.jar /app/agent_serving.jar
COPY --from=build-ui /build/dist /app/kb-ui-dist

# ── Python 服务代码 ──
COPY knowledge_mining/ ./knowledge_mining/
COPY llm_service/ ./llm_service/
COPY main_control_service/ ./main_control_service/
COPY mcp_server/ ./mcp_server/

# ── 共享配置与数据 ──
COPY .env .env.example ./
COPY domain_registry.yaml ./
COPY scenario_packs/ ./scenario_packs/
COPY databases/ ./databases/

# ── nginx + supervisord 配置 ──
COPY docker/nginx.conf /etc/nginx/sites-available/default
RUN rm -f /etc/nginx/sites-enabled/default \
    && ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default
COPY docker/supervisord.conf /etc/supervisor/conf.d/cmkb.conf

RUN mkdir -p /app/uploads /app/data/main_control_service

EXPOSE 80 8900 8901 8910 8081 9000

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf", "-n"]
