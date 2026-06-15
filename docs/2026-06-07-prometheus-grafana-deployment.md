# Prometheus + Grafana 监控部署（agent_serving_zdy）

> 目标：为 `agent_serving_zdy`（端口 8082）接上监控。应用侧的指标暴露已在「特性 1：检索 Pipeline 可观测性」中完成，本文只负责部署「抄数字的」（Prometheus）和「画图的」（Grafana）这两个进程。
> 现状：`agent_serving_zdy/docker-compose.yml` 目前只有 `agent-serving` 一个服务；`/actuator/prometheus` 端点已就绪（见 `application.yml` 的 `management` 段），但尚无 Prometheus 抓取、无 Grafana 看板。

---

## 1. 架构：三个独立进程

Prometheus 和 Grafana 不是嵌进 Java 应用的库，而是各自独立运行的服务器，通过网络互相访问：

```
agent-serving:8082  ──/actuator/prometheus──▶  Prometheus:9090  ──查询──▶  Grafana:3000
   (你的应用)            (被定时拉取)            (存时序 + 判告警)        (画图给人看)
```

- **应用**：每次检索时把运行事实写成内存中的 meter（`SearchMetrics`），通过 `/actuator/prometheus` 暴露。**pull 模式**——应用不主动推送，等 Prometheus 来抓。
- **Prometheus**：每 15s 来抓一次快照，存进自带时序数据库，并按规则判断是否告警。
- **Grafana**：连 Prometheus，把时序数据渲染成网页图表给人看。

---

## 2. 应用侧前置条件（已完成，无需改动）

`agent_serving_zdy/src/main/resources/application.yml`：

```yaml
management:
  endpoints:
    web:
      exposure:
        include: prometheus      # 仅暴露 prometheus 端点
  metrics:
    tags:
      application: agent-serving # 所有指标自动带 application 标签
```

> 注意：health 故意不在 exposure 列表里——`/actuator/health` 由自定义的 `HealthController` 提供，避免与 actuator 的 handler 冲突。

`pom.xml` 已含 `spring-boot-starter-actuator` + `micrometer-registry-prometheus`。

验证端点是否就绪（应用启动后）：

```bash
curl http://localhost:8082/actuator/prometheus | grep serving_
```

能看到 `serving_search_duration_ms`、`serving_query_intent_total` 等即正常。

---

## 3. 部署方式一：Docker Compose（推荐，适配当前项目）

### 3.1 在 `agent_serving_zdy/docker-compose.yml` 追加两个服务

接在现有 `services:` 下（与 `agent-serving` 同级），并在文件末尾追加 `volumes:` 段：

```yaml
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus          # 时序数据持久化
    restart: unless-stopped

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin       # 首次登录密码，生产请改
    volumes:
      - grafana-data:/var/lib/grafana         # 看板/配置持久化
    depends_on:
      - prometheus
    restart: unless-stopped

volumes:
  prometheus-data:
  grafana-data:
```

### 3.2 新建 `agent_serving_zdy/prometheus.yml`

告诉 Prometheus「去抓谁」：

```yaml
global:
  scrape_interval: 15s          # 每 15 秒抓一次

scrape_configs:
  - job_name: 'agent-serving'
    metrics_path: '/actuator/prometheus'   # 端点路径
    static_configs:
      - targets: ['agent-serving:8082']    # 用 compose 服务名，同网络互通
```

> **关键**：`targets` 写 `agent-serving:8082`（compose 服务名），不是 `localhost`——同一 compose 网络下用服务名互相寻址。

### 3.3 启动与访问

```bash
cd agent_serving_zdy
docker compose up -d
```

| 服务 | 地址 | 说明 |
|------|------|------|
| 应用 | http://localhost:8082 | 业务 + `/actuator/prometheus` |
| Prometheus | http://localhost:9090 | 自带查询界面，可验证抓取 |
| Grafana | http://localhost:3000 | admin / admin 登录 |

**验证 Prometheus 抓到了**：访问 http://localhost:9090/targets ，`agent-serving` 这个 target 状态应为 `UP`。

### 3.4 Grafana 出图（两步）

1. **加数据源**：Connections → Data sources → Add → Prometheus，URL 填 `http://prometheus:9090`（compose 内用服务名），Save & Test。
2. **建看板**：New dashboard → Add visualization，选刚才的数据源，输入 PromQL 即可出图。

---

## 4. 可用指标速查（共 6 个）

| 指标 | 类型 | 标签 | 含义 |
|------|------|------|------|
| `serving_search_duration_ms` | histogram | — | 端到端延迟（含异常） |
| `serving_retrieval_candidates` | histogram | `route` | 每路检索候选数 |
| `serving_rerank_duration_ms` | histogram | — | rerank 阶段耗时 |
| `serving_rerank_fallback_total` | counter | `method`(model/llm/score) | 最终生效的 rerank 层 |
| `serving_query_intent_total` | counter | `intent` | 意图分布 |
| `serving_scope_empty_total` | counter | — | scope 为空且无结果次数 |

> 所有指标都自动带 `application="agent-serving"` 标签（来自 `application.yml` 的 `metrics.tags`）。

### 常用 PromQL 示例

```promql
# 搜索延迟 P99（5 分钟窗口）
histogram_quantile(0.99, sum(rate(serving_search_duration_ms_bucket[5m])) by (le))

# 意图分布（每分钟增量）
sum(rate(serving_query_intent_total[1m])) by (intent)

# rerank 降级率 = 非 model 层占比（LLM Service 健康度信号）
sum(rate(serving_rerank_fallback_total{method!="model"}[5m]))
  / sum(rate(serving_rerank_fallback_total[5m]))

# 各路平均候选数
sum(rate(serving_retrieval_candidates_sum[5m])) by (route)
  / sum(rate(serving_retrieval_candidates_count[5m])) by (route)
```

---

## 5. 告警示例

在 `prometheus.yml` 引入规则文件，或用 Alertmanager。典型规则：

```yaml
groups:
  - name: agent-serving
    rules:
      # rerank 持续降级 → LLM Service 可能异常
      - alert: RerankFallbackHigh
        expr: |
          sum(rate(serving_rerank_fallback_total{method!="model"}[5m]))
            / sum(rate(serving_rerank_fallback_total[5m])) > 0.5
        for: 5m
        labels: { severity: warning }
        annotations:
          summary: "rerank 降级率 > 50% 持续 5 分钟，疑似 LLM Service 故障"

      # 搜索延迟过高
      - alert: SearchLatencyHigh
        expr: |
          histogram_quantile(0.99,
            sum(rate(serving_search_duration_ms_bucket[5m])) by (le)) > 2000
        for: 5m
        labels: { severity: warning }
        annotations:
          summary: "搜索 P99 延迟 > 2s 持续 5 分钟"
```

---

## 6. 部署方式二：Kubernetes（生产主流）

不手写上述 YAML，用现成的 Helm chart 一把装好 Prometheus + Grafana + Alertmanager：

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install monitoring prometheus-community/kube-prometheus-stack
```

应用侧只需加一个 `ServiceMonitor` 资源声明指标位置，Prometheus 自动发现抓取，无需手维护 `targets`：

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: agent-serving
  labels:
    release: monitoring          # 与 kube-prometheus-stack 的 selector 对齐
spec:
  selector:
    matchLabels:
      app: agent-serving         # 匹配应用 Service 的 label
  endpoints:
    - port: http                 # Service 暴露 8082 的端口名
      path: /actuator/prometheus
      interval: 15s
```

---

## 7. 部署方式三：托管服务（免运维）

只暴露端点，存储/告警交给 SaaS：

- **Grafana Cloud**（有免费额度，小项目够用）
- 阿里云 ARMS、AWS Managed Prometheus 等

适合不想自己管 Prometheus 存储扩容、Grafana 升级的团队。

---

## 8. 部署要点 / 坑

1. **数据持久化**：Prometheus、Grafana 都要挂 volume（上文已配 `prometheus-data` / `grafana-data`），否则容器重启后历史数据和看板全丢。
2. **抓取间隔 vs 存储**：`scrape_interval` 越短越细但越占空间，15s 是常见默认。Prometheus 默认只留 15 天，长期保留需配 `--storage.tsdb.retention.time` 或接远端存储。
3. **网络可达**：Prometheus 必须能访问应用的 8082。同 compose 网络无需额外配置；跨机部署要放行防火墙，且别让网关挡掉 `/actuator/prometheus`。
4. **端点安全**：`/actuator/prometheus` 含 JVM 内部信息，不要裸暴露公网。生产环境只在内网开放，或加 basic auth / NetworkPolicy 限制仅 Prometheus 可访问。
5. **前端不要直接调端点**：它返回的是 Prometheus 文本格式（非 JSON）、只有当前快照（无历史）、且包含全部 JVM 指标。看板用 Grafana；产品页面要展示业务数据应由后端另开 JSON API。

---

## 9. 最小落地清单

对当前项目，跑通整套监控只需 3 步、改/加 2 个文件，**应用代码零改动**：

- [ ] 在 `agent_serving_zdy/docker-compose.yml` 追加 `prometheus` + `grafana` 服务和 `volumes` 段（§3.1）
- [ ] 新建 `agent_serving_zdy/prometheus.yml`（§3.2）
- [ ] `docker compose up -d`，访问 9090/targets 确认 UP，再进 Grafana 配数据源出图（§3.3–3.4）
