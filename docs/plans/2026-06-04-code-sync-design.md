# 设计文档：Python 服务代码同步

> 日期：2026-06-04
> 状态：已批准

## 1. 背景

服务器部署采用 Docker + volume bind mount 模式，Python 服务目录从宿主机挂载到容器内：

```yaml
volumes:
  - ./knowledge_mining:/app/knowledge_mining
  - ./llm_service:/app/llm_service
  - ./main_control_service:/app/main_control_service
  - ./mcp_server:/app/mcp_server
```

更新宿主机文件后 `supervisorctl restart` 即可生效。当前更新代码需要本地构建 Docker 镜像重新部署，流程较重。

## 2. 目标

在前端系统设置页增加"代码同步"功能，一键从 GitHub 拉取最新 Python 代码覆盖到运行目录，无需重新构建镜像。

## 3. 方案：GitHub Archive API

- 下载 `https://github.com/fzl194/KnowledgeBase/archive/refs/heads/master.tar.gz`（公开仓库，无需 token）
- 用 Python `tarfile` 解压，只提取白名单目录
- 无需服务器安装 git

## 4. 覆盖规则

### 覆盖（代码目录）

| 目录 | 说明 |
|------|------|
| `knowledge_mining/` | 挖掘服务，全覆盖 |
| `llm_service/` | LLM 服务，全覆盖 |
| `main_control_service/`（排除 config/） | 主控服务，只更新代码文件 |
| `mcp_server/` | MCP 服务，全覆盖 |

### 不覆盖（配置和数据）

| 文件/目录 | 说明 |
|-----------|------|
| `.env` | 环境变量 |
| `domain_registry.yaml` | 域注册 |
| `scenario_packs/` | 场景包 |
| `databases/` | 数据库 schema |
| `db_tables.py` / `reset_db.py` 等 | DB 管理脚本 |
| `docker-compose.yml` | 部署配置 |
| `main_control_service/config/` | 主控服务运行时配置 |

## 5. API 设计

### `POST /api/v1/code-sync`

**流程**：

1. 下载 tarball 到 `/tmp/cmkb-sync-{timestamp}.tar.gz`（超时 60 秒）
2. 用 `tarfile` 打开，遍历成员
3. tarball 内路径格式：`KnowledgeBase-master/{dir}/...`
4. 白名单过滤：
   - 前缀匹配 `*/knowledge_mining/`、`*/llm_service/`、`*/mcp_server/`
   - 匹配 `*/main_control_service/` 但排除 `*/main_control_service/config/`
5. 解压到 `/app/{dir}/`，覆盖同名文件
6. 清理临时文件
7. 返回结果

**请求**：无参数

**响应**：

```json
{
  "ok": true,
  "updated_dirs": ["knowledge_mining", "llm_service", "main_control_service", "mcp_server"],
  "file_count": 42,
  "commit_sha": "abc1234"
}
```

**错误响应**：

```json
{
  "ok": false,
  "error": "下载失败: Connection timeout"
}
```

**安全约束**：

- 路径遍历检查：跳过包含 `..` 的 tar 成员
- 白名单外的文件一概跳过
- 解压失败不回滚（覆盖模式，旧文件大部分保留）

## 6. 前端设计

在 `SettingsView.vue` 新增 `代码同步` tab：

- 显示 4 个可同步目录列表
- "同步最新代码"按钮
- 点击后调用 `POST /api/v1/code-sync`，显示 loading
- 返回后显示：更新了哪些目录、文件数、commit SHA
- 提示："代码已更新，请手动重启服务生效"

## 7. 不做的事情

- 不自动重启服务
- 不支持指定分支（固定 master）
- 不做 diff 展示（只显示更新统计）
- 不覆盖 Java 服务和前端（仍需 Docker 重新构建）
- 不回滚机制（覆盖模式）
