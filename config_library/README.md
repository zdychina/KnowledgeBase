# 独立配置库

本目录保存按部署场景维护的配置，不进入 Docker 构建上下文。

当前配置：

- `site/`：站点知识库，启用 `civil_engineering` 和 `odn` domain。
- `enterprise/`：政企招投标文档知识库，仅启用 `tender_rfp` domain。

手工部署政企配置时：

1. 备份服务器当前的 `main_control_service/config/domain_registry.yaml`。
2. 将 `enterprise/domain_registry.yaml` 复制到上述位置。
3. 将 `enterprise/scenario_packs/tender_rfp/` 复制到服务器的
   `main_control_service/config/scenario_packs/tender_rfp/`。
4. 如需严格隔离场景，删除服务器配置目录中其他 scenario pack；不要删除源代码仓库中的配置。
5. 通过服务器环境变量提供数据库密码，不要在本配置库中写入真实密码。

复制后重启 Main Control、Mining 和 Serving 服务。

站点配置采用相同的复制方式，将 `site/domain_registry.yaml` 和
`site/scenario_packs/` 下的两个 domain 覆盖到运行时配置目录即可。

