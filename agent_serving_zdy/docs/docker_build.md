# agent-serving Docker 镜像构建与运行

> 模块：`agent_serving_zdy`  
> 镜像产物：`coremasterkb/agent-serving:0.1.0`  
> 服务端口：`8082`

---

## 一、前置条件

| 依赖 | 最低版本 | 说明 |
|------|----------|------|
| Docker | 24.x | `docker --version` |
| Docker Compose | 2.x (`docker compose`) | `docker compose version` |
| 网络 | 可访问 Maven Central | 构建阶段拉取依赖 |

构建时不需要本地安装 JDK 或 Maven，全部在容器内完成。

---

## 二、目录结构要求

运行前确认仓库根目录下以下文件存在：

```
CoreMasterKB/                        ← 仓库根目录
├── domain_registry.yaml             ← 必须存在（运行时 volume 挂载）
├── scenario_packs/                  ← 必须存在（运行时 volume 挂载）
│   ├── cloud_core_network/
│   │   └── domain.yaml
│   └── generic/
│       └── domain.yaml
└── agent_serving_zdy/               ← 所有 Docker 操作在此目录执行
    ├── Dockerfile
    ├── docker-compose.yml
    ├── .env.example
    └── src/
```

---

## 三、准备 .env 文件

在 `agent_serving_zdy/` 目录下，复制示例文件并填写真实配置：

```bash
cd agent_serving_zdy
cp .env.example .env
```

编辑 `.env`，填写以下关键字段：

```properties
# PostgreSQL 连接
PG_HOST=192.168.1.100        # PostgreSQL 服务器 IP，不能用 localhost（容器内不通）
PG_PORT=5432
PG_DBNAME=coremasterkb
PG_USER=zdy
PG_PASSWORD=your-password

# 各 domain 数据库连接 URL（Key 名来自 domain_registry.yaml → database_url_env）
COREMASTERKB_DB_CLOUD_CORE=jdbc:postgresql://192.168.1.100:5432/cloud_core_network_db?user=zdy&password=your-password
COREMASTERKB_DB_GENERIC=jdbc:postgresql://192.168.1.100:5432/generic_db?user=zdy&password=your-password

# LLM / Embedding / Rerank 服务
LLM_SERVICE_URL=http://192.168.1.100:8900
EMBEDDING_MODEL=embedding-3
EMBEDDING_DIMENSIONS=1024
RERANK_MODEL=rerank-pro
```

> **注意**：`.env` 已在 `.dockerignore` 中排除，不会打入镜像。每台部署机器单独维护此文件。

---

## 四、构建镜像

### 方式 A：docker compose（推荐，构建 + 启动一步完成）

```bash
# 在 agent_serving_zdy/ 目录下执行
cd agent_serving_zdy

docker compose up --build -d
```

- `--build`：每次强制重新构建镜像
- `-d`：后台运行

### 方式 B：单独构建镜像（不启动）

```bash
cd agent_serving_zdy

docker build -t coremasterkb/agent-serving:0.1.0 .
```

构建完成后验证镜像：

```bash
docker images | grep agent-serving
```

### 方式 C：构建后手动 docker run

```bash
cd agent_serving_zdy

docker build -t coremasterkb/agent-serving:0.1.0 .

docker run -d \
  --name agent-serving \
  -p 8082:8082 \
  --env-file .env \
  -e DOMAIN_REGISTRY_PATH=/app/config/domain_registry.yaml \
  -e SCENARIO_PACKS_DIR=/app/config/scenario_packs \
  -v "$(pwd)/../domain_registry.yaml:/app/config/domain_registry.yaml:ro" \
  -v "$(pwd)/../scenario_packs:/app/config/scenario_packs:ro" \
  --restart unless-stopped \
  coremasterkb/agent-serving:0.1.0
```

> Windows PowerShell 下将 `$(pwd)` 替换为 `${PWD}`。

---

## 五、验证服务

### 1. 查看启动日志

```bash
docker compose logs -f agent-serving
```

正常启动后会出现：

```
Started AgentServingApplication in X.XXX seconds
```

### 2. 健康检查

```bash
curl http://localhost:8082/actuator/health
```

预期返回：

```json
{"status":"ok","version":"0.1.0"}
```

---

## 六、常用运维命令

```bash
# 查看运行状态
docker compose ps

# 查看实时日志
docker compose logs -f agent-serving

# 停止服务（保留容器）
docker compose stop

# 停止并删除容器
docker compose down

# 重新构建并重启（代码更新后使用）
docker compose up --build -d

# 进入容器调试
docker compose exec agent-serving sh

# 查看镜像大小
docker image inspect coremasterkb/agent-serving:0.1.0 --format='{{.Size}}' | awk '{printf "%.0f MB\n", $1/1024/1024}'
```

---

## 七、常见问题

### Q1: 构建时 Maven 依赖下载失败

原因：Maven Central 网络不通，或 `jieba-analysis` 依赖找不到。

解决：
```bash
# 确认网络可达
docker run --rm maven:3.9.6-eclipse-temurin-21 mvn --version

# 如需配置 Maven 镜像源，在 Dockerfile builder 阶段 COPY 一个 settings.xml
```

### Q2: 容器启动后立即退出

```bash
# 查看退出原因
docker compose logs agent-serving
```

常见原因：
- PostgreSQL 连接失败 → 检查 `.env` 中 `PG_HOST` 是否为真实 IP，不能用 `localhost`
- `domain_registry.yaml` 路径不存在 → 确认 volume 挂载路径正确

### Q3: 端口冲突

```bash
# 检查 8082 端口占用
netstat -ano | findstr 8082        # Windows
lsof -i :8082                      # Linux/Mac

# 临时改端口：修改 docker-compose.yml 中 ports 为 "8083:8082"
```

### Q4: Windows 路径下 volume 挂载失败

在 Windows 上，确保 Docker Desktop 开启了对应盘符的文件共享：  
`Settings → Resources → File sharing` → 添加 `D:\`

---

## 八、镜像分层说明

```
eclipse-temurin:21-jre-jammy   ← 基础层（约 220MB）
  └── appuser 用户创建
      └── /app/config/ 目录
          └── app.jar            ← 应用 fat jar（约 50MB）
```

domain_registry.yaml 和 scenario_packs/ **不打入镜像**，通过 volume 在运行时注入，更新配置无需重新构建镜像。
