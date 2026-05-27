# CoreMasterKB

## Docker 部署

### 服务架构

单容器 All-in-One，6 个服务通过 supervisord 管理：

| 服务 | 容器内端口 | 说明 |
|------|-----------|------|
| nginx | 80 | 前端静态文件 + API 反向代理 |
| knowledge_mining | 8901 | 知识挖掘 |
| llm_service | 8900 | LLM 运行时 |
| main_control_service | 8910 | 主控配置中心 |
| agent_serving_java | 8081 | 检索服务 |
| mcp_server | 9000 | MCP 服务 |

前端通过 nginx 代理访问后端 API（`/api/mining`、`/api/serving`、`/api/llm`、`/api/control-plane`），不依赖 localhost。

### 本机构建

```bash
bash deploy-build.sh
```

生成 `cmkb.tar`（约 203MB）。

### 服务器部署

**传文件**：将以下文件传到服务器同一目录：

- `cmkb.tar`
- `docker-compose.yml`
- `deploy-server.sh`

**docker-compose.yml 注意**：服务器上需要切换两处配置：

1. **镜像来源**：注释掉 `build` 块，取消注释 `image: coremasterkb-app:latest`
2. **volume 挂载**：取消注释代码和配置挂载（本地开发可保持注释，直接用镜像内置代码）

yml 文件内有详细注释标注哪几行是本地、哪几行是服务器。

**执行部署**：

```bash
# 首次部署 或 强制用镜像版本覆盖所有代码
bash deploy-server.sh --force

# 后续只更新镜像，不覆盖本地改过的代码
bash deploy-server.sh
```

### 服务器管理

```bash
# 查看服务状态
docker compose exec app supervisorctl status

# 重启某个服务
docker compose exec app supervisorctl restart mining

# 重启所有服务
docker compose exec app supervisorctl restart all

# 查看日志
docker compose logs -f --tail 50

# 进入容器
docker compose exec app bash

# 停止 / 启动
docker compose down
docker compose up -d
```

### 代码更新

**Python 代码**：通过 volume 挂载，改宿主机文件后重启服务即可：

```bash
docker compose exec app supervisorctl restart mining
```

**Java / 前端**：需要重新构建镜像：

```bash
# 本机
bash deploy-build.sh

# 传 cmkb.tar 到服务器后
bash deploy-server.sh --force
```

### 配置文件

- `.env` — 数据库连接、API Key 等
- `domain_registry.yaml` — 领域注册

部署脚本会从镜像拷出这些文件到宿主机，可直接编辑。
