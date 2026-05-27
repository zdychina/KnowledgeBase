# CoreMasterKB 统一知识库前端规划

> 版本：v1.0
> 日期：2026-05-19
> 位置：`kb-ui/`（项目根目录，与 Mining/Serving/LLM 平级）
> 状态：规划，待审核

---

## 一、目标

为 CoreMasterKB 构建**统一的知识库管理前端**，面向多个 domain 的知识资产管理和检索监控。

核心目标：
1. **多 Domain 统一管理**：同一前端切换不同 domain（cloud_core_network / ip_network / generic），后端参数随 domain 自动切换
2. **Mining 流程可视化**：作业提交、Pipeline 阶段进度、文档处理状态、队列深度
3. **Serving 检索调试**：查询测试、结果分析、debug 面板、性能监控
4. **知识资产浏览**：文档、段落、检索单元、实体关系图谱的可视化浏览
5. **LLM Service 监控**：任务队列、延迟分布、token 消耗、成功率
6. **系统健康监控**：全局仪表盘、各服务状态、关键指标趋势

---

## 二、设计原则

### 2.1 工业级标准

参考 Dify、FastGPT、NVIDIA RAG Blueprint 的管理界面模式：

| 原则 | 说明 |
|------|------|
| **信息密度高** | 管理后台不是消费级产品，表格/图表/状态指示器要紧凑 |
| **状态一目了然** | 颜色编码（绿/黄/红）+ 数字 + 趋势箭头 |
| **操作路径短** | 核心操作不超过 3 次点击 |
| **实时感** | 运行中的任务自动刷新进度，不需要手动 F5 |
| **可调试** | 检索测试带完整 debug 面板，Pipeline 可追踪 |

### 2.2 视觉方向

- **亮色主题为主**，深色主题可选（不在 Phase 1）
- 配色参考工业级管理后台（Grafana / Datadog / Dify）：
  - 主色：专业蓝 `#3b6fdb`
  - 背景：`#f8f9fb`（页面）+ `#ffffff`（卡片）
  - 状态色：绿 `#16a34a` / 黄 `#ca8a04` / 红 `#dc2626`
  - 字体：系统字体栈，数据表格用等宽字体
- **不使用**：花哨渐变、3D 效果、动画过度

### 2.3 多 Domain 架构

```
前端全局状态：
  currentDomain: "cloud_core_network"
  domainConfig: {
    cloud_core_network: {
      miningApi: "http://localhost:8901",
      servingApi: "http://localhost:8081",
      llmApi: "http://localhost:8900",
      active: true,
    },
    ip_network: {
      miningApi: "http://localhost:8902",
      servingApi: "http://localhost:8082",
      llmApi: "http://localhost:8900",
      active: true,
    },
    generic: {
      miningApi: "http://localhost:8903",
      servingApi: "http://localhost:8083",
      llmApi: "http://localhost:8900",
      active: false,
    }
  }

切换 domain 时：
  → API base URL 变更
  → 所有数据重新加载
  → URL 同步变更（/cloud_core_network/mining）
```

不同 domain 的后端端口、配置不同，前端通过 domain 配置表自动路由。domain 配置从前端 settings 管理，存入 localStorage（后续可对接 domain_registry.yaml）。

---

## 三、技术选型

| 选择 | 方案 | 理由 |
|------|------|------|
| 框架 | **Vue 3 + Vite + TypeScript** | 轻量、适合管理后台、中文生态好 |
| UI 库 | **Element Plus** | 企业级管理后台标配，表格/表单/图表组件齐全 |
| 图可视化 | **AntV G6** | 知识图谱力导向图，支持大规模节点交互 |
| 图表 | **ECharts** | 监控图表（折线图、饼图、直方图、热力图） |
| 状态管理 | **Pinia** | Vue 3 官方推荐 |
| 路由 | **Vue Router 4** | 支持 domain 前缀路由 |
| HTTP | **Axios** | 统一拦截器处理 domain 切换 |
| CSS | **UnoCSS** 或原生 CSS 变量 | 轻量、按需生成 |
| 代码位置 | `kb-ui/` | 与 agent_serving_fzl / knowledge_mining_fzl / llm_service 平级 |

---

## 四、页面规划

### 4.0 全局布局

```
┌─────────────────────────────────────────────────────────────┐
│  CoreMasterKB     [cloud_core_network ▾]    [●Mining ●Serving ●LLM] │
├──────────┬──────────────────────────────────────────────────┤
│          │                                                  │
│  概览    │  主内容区                                         │
│  挖掘    │                                                  │
│  检索    │                                                  │
│  知识资产 │                                                  │
│  LLM服务 │                                                  │
│  系统设置 │                                                  │
│          │                                                  │
└──────────┴──────────────────────────────────────────────────┘
```

**头部**：
- 左侧：Logo + 产品名
- 中间：**Domain 选择器**（下拉框，切换 domain）
- 右侧：三个服务健康状态指示灯（绿色/黄色/红色点）

**侧边栏**：
- 可折叠（图标模式/文字模式）
- 当前选中菜单高亮
- 底部：版本信息

### 4.1 概览仪表盘 (`/:domain/`)

系统全局状态，一屏掌握当前 domain 的健康状况和关键指标。

```
┌─────────────────────────────────────────────────────────┐
│  Domain: cloud_core_network                              │
├──────────┬──────────┬──────────┬──────────┬────────────┤
│ 📄 文档  │ 📝 段落  │ 🔍 检索单元│ 🔗 关系  │ ⚡ Active  │
│ 12      │ 342      │ 186      │ 89       │ Release    │
│ +2 ↑    │ stable   │ +15 ↑    │ -40% ↓  │ rls_018    │
├──────────┴──────────┴──────────┴──────────┴────────────┤
│                                                         │
│  ┌── 服务状态 ──────────────────────────────────────┐  │
│  │ Mining API  ● OK  │ Serving API  ● OK  │ LLM  ● OK │  │
│  │ DB 连接池 3/10    │ P95 延迟 1.2s    │ 运行中 3   │  │
│  └──────────────────────────────────────────────────┘  │
│                                                         │
│  ┌── 最近 Mining Runs ────────┐ ┌── 检索趋势 (7天) ──┐ │
│  │ run_018 ⏳ 60%  3m24s      │ │ ───────────╮       │ │
│  │ run_017 ✅ 完成  5m12s     │ │      ╱╲    ╱╲      │ │
│  │ run_016 ✅ 完成  7m45s     │ │     ╱  ╲  ╱  ╲     │ │
│  │ run_015 ❌ 失败  2m03s     │ │────╱    ╲╱    ╲────│ │
│  └────────────────────────────┘ └─────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**数据来源**（domain 切换时 API base URL 变更）：
- Mining `/api/knowledge/stats` → 资产统计
- Mining `/health` → Mining 健康
- Serving `/health` → Serving 健康
- LLM `/dashboard/api/stats` → LLM 统计
- Mining `/api/runs?limit=5` → 最近 runs

### 4.2 挖掘管理 (`/:domain/mining`)

#### 4.2.1 Mining Runs 列表

```
┌──────────────────────────────────────────────────────────────┐
│ Mining Runs                              [新建 Run] [刷新]    │
├──────────┬─────────┬────────┬──────────┬──────────┬────────┤
│ Run ID   │ 状态    │ 文档数  │ 耗时     │ Build    │ 操作   │
├──────────┼─────────┼────────┼──────────┼──────────┼────────┤
│ run_018  │ ⏳ 运行中│ 7/12   │ 3m 24s   │ -        │ [取消] │
│ run_017  │ ✅ 完成  │ 8/8    │ 5m 12s   │ bld_017  │ [发布] │
│ run_016  │ ✅ 已发布│ 15/15  │ 7m 45s   │ bld_016  │ [查看] │
│ run_015  │ ❌ 失败  │ 3/10   │ 2m 03s   │ -        │ [重试] │
└──────────┴─────────┴────────┴──────────┴──────────┴────────┘
```

#### 4.2.2 Run 详情 — Pipeline 阶段时间线

```
┌──────────────────────────────────────────────────────┐
│ Run run_018 详情                           [返回列表] │
├──────────────────────────────────────────────────────┤
│                                                      │
│ Pipeline 进度                                        │
│ ┌──────┐    ┌──────────┐    ┌───────┐    ┌───────┐  │
│ │parse │ ──→│ segment  │ ──→│enrich │ ──→│relation│  │
│ │ ✅   │    │ ✅       │    │ ⏳ 60%│    │ ⬚     │  │
│ │0.8s  │    │2.1s      │    │ 1m24s │    │pending │  │
│ └──────┘    └──────────┘    └───────┘    └───────┘  │
│                                  ↓                   │
│                         ┌──────────────────┐         │
│                         │ 当前: enrich     │         │
│                         │ 进度: 7/12 文档   │         │
│                         │ LLM: 23/48 调用   │         │
│                         │ 耗时: 1m 24s      │         │
│                         └──────────────────┘         │
│                                                      │
│ 文档处理结果                                          │
│ ┌─────────────────┬────────┬────────┬──────────────┐│
│ │ 文档名          │ 操作   │ 状态   │ 说明         ││
│ ├─────────────────┼────────┼────────┼──────────────┤│
│ │ SMF配置指南.md  │ new    │ ✅     │ 新增 37 段落 ││
│ │ UPF管理.md      │ update │ ✅     │ 更新 3 段落  ││
│ │ AMF操作手册.md  │ new    │ ⏳ 60% │ 处理中       ││
│ │ N4接口.md       │ skip   │ ⬚      │ 等待中       ││
│ └─────────────────┴────────┴────────┴──────────────┘│
└──────────────────────────────────────────────────────┘
```

**实时更新**：run 状态为 running 时，3 秒轮询自动刷新阶段进度。阶段完成时自动高亮跳转。

#### 4.2.3 新建 Mining Run

```
┌──────────────────────────────────────────────────┐
│ 新建 Mining Run                                  │
├──────────────────────────────────────────────────┤
│ Domain: cloud_core_network  (自动填充，只读)      │
│                                                  │
│ 输入路径:    [/path/to/documents    ] [浏览]      │
│ Domain Pack: [cloud_core_network ▾ ]             │
│ 最大并行数:  [4 ▾]                               │
│                                                  │
│ 高级设置 ▾                                       │
│ ├─ 仅 Phase 1:  [ ]                              │
│ ├─ 部分失败仍发布: [ ]                            │
│ ├─ LLM Service: [http://localhost:8900]          │
│ └─ Embedding:   [embedding-3 ▾]  [1024 维]       │
│                                                  │
│                           [取消]  [开始挖掘]      │
└──────────────────────────────────────────────────┘
```

**数据来源**：
- `POST /api/runs` → 提交 run
- `GET /api/runs` → 列表
- `GET /api/runs/{id}` → 详情
- `GET /api/runs/{id}/stages` → 阶段时间线
- `GET /api/runs/{id}/documents` → 文档处理结果
- `POST /api/runs/{id}/cancel` → 取消
- `POST /api/runs/{id}/publish` → 发布

### 4.3 知识检索测试 (`/:domain/search`)

```
┌──────────────────────────────────────────────────────────────┐
│ 知识检索测试                                                  │
│ ┌──────────────────────────────────────┐  [domain_pack ▾]   │
│ │ SMF ADD UPF 的步骤是什么             │  [debug ✓] [检索]   │
│ └──────────────────────────────────────┘                     │
│                                                              │
│ ┌─ 检索概览 ───────────────────────────────────────────────┐│
│ │ 耗时: 1.2s | Items: 12 | Relations: 8 | Sources: 4      ││
│ │ Intent: command_usage | Entities: [SMF, UPF, ADD]       ││
│ └──────────────────────────────────────────────────────────┘│
│                                                              │
│ [结果] [关系图] [来源文档] [Debug]                            │
│                                                              │
│ ┌─ 结果列表 ──────────────────────────────────────────────┐ │
│ │ 1. ⭐ seed │ command_usage │ ADD UPF 命令说明     0.95  │ │
│ │    SMF配置指南 §3.2 │ 256 token                     │ │
│ │ 2. ⭐ seed │ procedure     │ UPF注册流程          0.89  │ │
│ │    UPF管理手册 §2.1 │ 189 token                     │ │
│ │ 3. 📎 expansion │ concept  │ SMF 概述              0.82│ │
│ │    SMF配置指南 §1.1 │ 312 token                     │ │
│ │ ...                                                     │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                              │
│ ┌─ Debug 面板 (可折叠) ──────────────────────────────────┐  │
│ │ Pipeline: 10 步, 总耗时 1.2s                            │  │
│ │ Step 1: Load Domain Profile     0.01s                   │  │
│ │ Step 2: Query Understanding     0.35s  → command_usage  │  │
│ │ Step 3: Retrieval Router        0.01s  → BM25+Dense    │  │
│ │ Step 4: Resolve Active Scope    0.02s  → 12 snapshots  │  │
│ │ Step 5: Generate Query Embed    0.08s                   │  │
│ │ Step 6: Retrieve                0.31s  → BM25:50 Dense:30│
│ │ Step 7: Fuse (weighted_rrf)     0.01s  → 40 items      │  │
│ │ Step 8: Rerank (zhipu)          0.38s  → 12 items      │  │
│ │ Step 9: Assemble ContextPack    0.04s  → pack assembled │  │
│ │ Step 10: Build Debug Info       0.00s                   │  │
│ └─────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

**数据来源**：
- Serving `POST /api/v1/search` → 检索结果 + debug（请求中带 domain 参数）

### 4.4 知识资产浏览 (`/:domain/knowledge`)

#### 4.4.1 资产统计概览

```
┌───────────────────────────────────────────────────────┐
│ 知识资产                            [刷新]            │
│                                                       │
│ ┌──────────┬──────────┬──────────┬──────────┐        │
│ │ 📄 文档  │ 📝 段落  │ 🔍 检索单元│ 🔗 关系  │        │
│ │ 12      │ 342      │ 186      │ 89       │        │
│ └──────────┴──────────┴──────────┴──────────┘        │
│                                                       │
│ [文档列表] [段落列表] [检索单元] [关系图] [实体列表]    │
└───────────────────────────────────────────────────────┘
```

#### 4.4.2 文档列表

```
┌─────────────────────────────────────────────────────────────┐
│ 文档列表                              [类型过滤 ▾] [搜索]    │
├──────────────┬─────────┬────────┬──────────┬───────────────┤
│ 文档名       │ 类型    │ 段落数  │ 快照数   │ 创建时间      │
├──────────────┼─────────┼────────┼──────────┼───────────────┤
│ SMF配置指南  │ markdown│ 37     │ 2        │ 2026-05-18    │
│ UPF管理手册  │ markdown│ 24     │ 1        │ 2026-05-17    │
│ AMF操作手册  │ markdown│ 31     │ 1        │ 2026-05-17    │
│ N4接口文档   │ markdown│ 18     │ 1        │ 2026-05-16    │
└──────────────┴─────────┴────────┴──────────┴───────────────┘
```

#### 4.4.3 文档详情

```
┌──────────────────────────────────────────────────────┐
│ SMF 配置指南                          [返回文档列表]  │
│ 类型: markdown | 快照: 2 | 创建: 2026-05-18          │
├──────────────────────────────────────────────────────┤
│ [段落] [检索单元] [关系]                              │
│                                                      │
│ #  │ 类型     │ 标题        │ 语义角色     │ Token │
│ 1  │ heading  │ SMF 概述    │ -           │ 12    │
│ 2  │ paragraph│ SMF是会话.. │ concept     │ 256   │
│ 3  │ table    │ 接口列表    │ parameter   │ 89    │
│ 4  │ code     │ ADD NE 示例│ example     │ 45    │
│ ...                                                  │
│                                                      │
│ 点击段落展开完整内容:                                  │
│ ┌──────────────────────────────────────────────────┐ │
│ │ [segment #2] SMF 是会话管理功能...               │ │
│ │ 实体: [SMF, 会话管理, N4]                        │ │
│ │ 检索单元: raw_text, entity_card(SMF)             │ │
│ │ 关系: ──依赖──→ UPF, ──包含──→ N4接口           │ │
│ └──────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

#### 4.4.4 知识图谱

```
┌──────────────────────────────────────────────────────────┐
│ 知识图谱                            [类型过滤 ▾] [搜索]   │
│                                                          │
│ 工具栏: [+放大] [-缩小] [重置] [力导向/层级切换] [全屏]   │
│                                                          │
│            ┌───┐                                         │
│    ┌───────│SMF│───────┐                                 │
│    │ 依赖  └─┬─┘ 关联  │                                 │
│    ↓         │         ↓                                 │
│  ┌───┐    包含      ┌───┐                                │
│  │UPF│      ↓       │AMF│                                │
│  └─┬─┘  ┌─────┐     └───┘                                │
│    │    │N4接口│                                         │
│    │    └──┬──┘                                          │
│    │  包含  │                                             │
│    ↓       ↓                                             │
│  ┌──────┐ ┌──────┐                                       │
│  │参数组│ │心跳配置│                                      │
│  └──────┘ └──────┘                                       │
│                                                          │
│ ┌─ 节点详情 ─────────────────────┐                       │
│ │ SMF (网元)                      │                       │
│ │ 类型: network_element           │                       │
│ │ 关联文档: 3                     │                       │
│ │ 关系: 依赖→UPF, 包含→N4, 关联→AMF│                       │
│ └─────────────────────────────────┘                       │
└──────────────────────────────────────────────────────────┘
```

**数据来源**（全部从 Mining API 读取，domain 由前端路由参数决定）：
- Mining `/api/knowledge/documents` → 文档列表
- Mining `/api/knowledge/documents/{id}` → 文档详情
- Mining `/api/knowledge/documents/{id}/segments` → 段落
- Mining `/api/knowledge/documents/{id}/units` → 检索单元
- Mining `/api/knowledge/relations` → 关系
- Mining `/api/knowledge/stats` → 统计

### 4.5 LLM Service 监控 (`/:domain/llm`)

```
┌──────────────────────────────────────────────────────────┐
│ LLM Service 监控                                         │
├──────────┬──────────┬──────────┬──────────┬─────────────┤
│ 总任务   │ 成功率   │ 运行中   │ Tokens   │ Avg 延迟    │
│ 1,248   │ 96.8%   │ 3       │ 524K    │ 1.2s       │
├──────────┴──────────┴──────────┴──────────┴─────────────┤
│                                                          │
│ ┌── 任务类型分布 ──────┐  ┌── 延迟分布 (24h) ──────────┐ │
│ │                      │  │                            │ │
│ │  chat    45%         │  │  P50: 0.8s                │ │
│ │  embed   35%         │  │  P95: 2.3s                │ │
│ │  rerank  20%         │  │  P99: 4.1s                │ │
│ │                      │  │  ═══════════════════       │ │
│ └──────────────────────┘  └────────────────────────────┘ │
│                                                          │
│ ┌── 最近任务 ──────────────────────────────────────────┐ │
│ │ [类型 ▾] [状态 ▾] [搜索...]                          │ │
│ │                                                      │ │
│ │ task_xxx │ embed  │ cloud_core │ ✅ │ 1.2s │ 2.4K tok│ │
│ │ task_yyy │ chat   │ cloud_core │ ⏳ │ --   │ --     │ │
│ │ task_zzz │ rerank │ cloud_core │ ❌ │ 3.8s │ 1.1K tok│ │
│ └──────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

**数据来源**：
- LLM Service `/dashboard/api/stats` → 统计
- LLM Service `/api/v1/results` → 结果列表

### 4.6 系统设置 (`/settings`)

```
┌──────────────────────────────────────────────────────┐
│ 系统设置                                              │
├──────────────────────────────────────────────────────┤
│ [Domain 管理] [服务配置] [关于]                        │
│                                                      │
│ Domain 管理:                                         │
│ ┌─────────────────┬────────┬────────┬──────────────┐│
│ │ Domain          │ 状态   │ Mining │ Serving      ││
│ ├─────────────────┼────────┼────────┼──────────────┤│
│ │ cloud_core_net  │ ✅ 启用│ :8901  │ :8081        ││
│ │ ip_network      │ ✅ 启用│ :8902  │ :8082        ││
│ │ generic         │ ⬚ 停用│ :8903  │ :8083        ││
│ └─────────────────┴────────┴────────┴──────────────┘│
│                                          [+ 添加 Domain]│
│                                                      │
│ 当前 Domain 配置 (cloud_core_network):                │
│   Mining API:  http://localhost:8901                 │
│   Serving API: http://localhost:8081                 │
│   LLM Service: http://localhost:8900                 │
│   DB:          postgresql://***:***@localhost:5432/..│
└──────────────────────────────────────────────────────┘
```

---

## 五、后端需要的改动

### 5.1 CORS 配置（P0，前端必须）

三个服务都需要添加 CORS：

**Mining API** (`knowledge_mining_fzl/mining/api/app.py`)：
```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
```

**Serving API** (`agent_serving_fzl`)：
```java
// Spring Boot CORS config
@Configuration
public class CorsConfig implements WebMvcConfigurer {
    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/api/**").allowedOrigins("*").allowedMethods("*");
    }
}
```

**LLM Service** (`llm_service`)：同 Mining，FastAPI 添加 CORS middleware。

### 5.2 新增 API 端点

| 服务 | 端点 | 说明 | 优先级 |
|------|------|------|--------|
| Mining | `GET /api/runs/{id}/progress` | 返回当前阶段实时进度（已处理/总数） | P1（Run 详情页需要） |
| Mining | `GET /api/knowledge/graph` | 返回全局图谱数据（节点+边），支持 domain 过滤 | P2（知识图谱页需要） |
| Serving | `GET /api/v1/stats` | 返回检索统计（请求数、延迟、缓存命中率） | P2（概览页需要） |

### 5.3 Mining API 参数调整

部分端点需要增加 domain 参数：
- `GET /api/knowledge/stats` → 增加 `?domain=xxx` 过滤
- `GET /api/knowledge/documents` → 增加 `?domain=xxx` 过滤
- `GET /api/runs` → 增加 `?domain=xxx` 过滤

当前数据库已有 domain 字段（多域统一计划），SQL 增加 WHERE domain = %s。

---

## 六、目录结构

```
kb-ui/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
├── .env.development              # 开发环境 API 地址
├── .env.production               # 生产环境 API 地址
├── src/
│   ├── main.ts                   # 入口
│   ├── App.vue                   # 根组件
│   ├── router/
│   │   └── index.ts              # 路由（含 domain 前缀）
│   ├── stores/
│   │   ├── domain.ts             # Domain 全局状态（切换、配置）
│   │   ├── mining.ts             # Mining 数据状态
│   │   ├── serving.ts            # Serving 数据状态
│   │   └── llm.ts                # LLM Service 数据状态
│   ├── api/
│   │   ├── client.ts             # Axios 实例（domain 切换自动变更 base URL）
│   │   ├── mining.ts             # Mining API 方法
│   │   ├── serving.ts            # Serving API 方法
│   │   └── llm.ts                # LLM Service API 方法
│   ├── views/
│   │   ├── DashboardView.vue     # 概览仪表盘
│   │   ├── mining/
│   │   │   ├── RunsView.vue      # Mining Runs 列表
│   │   │   ├── RunDetailView.vue # Run 详情（Pipeline 时间线）
│   │   │   └── CreateRunDialog.vue # 新建 Run 对话框
│   │   ├── SearchView.vue        # 检索测试
│   │   ├── knowledge/
│   │   │   ├── KnowledgeIndex.vue    # 资产统计概览
│   │   │   ├── DocumentsView.vue     # 文档列表
│   │   │   ├── DocumentDetailView.vue # 文档详情
│   │   │   └── GraphView.vue         # 知识图谱可视化
│   │   ├── LlmView.vue           # LLM Service 监控
│   │   └── SettingsView.vue      # 系统设置
│   ├── components/
│   │   ├── layout/
│   │   │   ├── AppLayout.vue     # 主布局（侧边栏+头部+内容）
│   │   │   ├── Sidebar.vue       # 侧边栏
│   │   │   ├── Header.vue        # 头部（domain 选择器+服务状态）
│   │   │   └── DomainSelector.vue # Domain 下拉选择器
│   │   ├── mining/
│   │   │   ├── PipelineTimeline.vue   # Pipeline 阶段可视化
│   │   │   ├── RunStatusBadge.vue     # Run 状态标签
│   │   │   ├── DocumentProcessTable.vue # 文档处理结果表
│   │   │   └── StageProgress.vue      # 单阶段进度条
│   │   ├── search/
│   │   │   ├── SearchInput.vue
│   │   │   ├── ResultList.vue
│   │   │   ├── RelationGraph.vue     # 检索结果关系子图
│   │   │   └── DebugPanel.vue        # Pipeline debug 面板
│   │   ├── knowledge/
│   │   │   ├── SegmentTable.vue
│   │   │   ├── UnitTable.vue
│   │   │   ├── SegmentDetail.vue     # 段落展开详情
│   │   │   └── KnowledgeGraph.vue    # 全局知识图谱（AntV G6）
│   │   ├── llm/
│   │   │   ├── TaskTable.vue
│   │   │   └── LatencyChart.vue
│   │   └── common/
│   │       ├── ServiceHealthBadge.vue # 服务健康状态徽章
│   │       ├── StatsCard.vue          # 统计卡片（数字+趋势）
│   │       └── EmptyState.vue         # 空状态占位
│   ├── composables/
│   │   ├── usePolling.ts         # 自动轮询（running 状态的 run）
│   │   ├── useDomain.ts          # Domain 切换逻辑
│   │   └── useApi.ts             # API 调用封装
│   ├── types/
│   │   ├── mining.ts             # Mining 数据类型
│   │   ├── serving.ts            # Serving 数据类型
│   │   └── llm.ts                # LLM 数据类型
│   └── styles/
│       ├── variables.css         # CSS 变量（亮色主题）
│       └── global.css            # 全局样式
├── .gitignore
└── README.md
```

---

## 七、路由设计

```
/:domain/                       → 概览仪表盘
/:domain/mining                 → Mining Runs 列表
/:domain/mining/runs/:runId     → Run 详情
/:domain/search                 → 检索测试
/:domain/knowledge              → 知识资产概览
/:domain/knowledge/documents    → 文档列表
/:domain/knowledge/documents/:id → 文档详情
/:domain/knowledge/graph        → 知识图谱
/:domain/llm                    → LLM Service 监控
/settings                       → 系统设置（全局，不随 domain 变）
```

Domain 切换时：
- URL 变更：`/cloud_core_network/mining` → `/ip_network/mining`
- API base URL 变更
- 数据重新加载
- 路由保持（如果在 mining 页面切换 domain，仍然在 mining 页面）

---

## 八、监控预留

### 8.1 数据采集点

| 位置 | 采集指标 | 存储 |
|------|---------|------|
| Mining Run 完成 | 耗时、文档数、段落数、关系数 | mining_runs 表 |
| Serving 检索 | 耗时、召回数、rerank 分数 | serving_query_log 表 |
| LLM Task 完成 | 耗时、token 数、状态 | agent_llm_tasks 表 |

### 8.2 监控面板预留

- **Mining 效率趋势**：每次 run 的耗时趋势图（ECharts 折线图）
- **检索质量趋势**：平均召回数、rerank 分数分布（ECharts 直方图）
- **LLM 延迟分布**：P50/P95/P99（ECharts 箱线图）
- **队列深度**：LLM 运行中任务数实时变化（ECharts 动态折线图）

### 8.3 动态队列展示

**Mining Run 实时进度**：
- 使用 `usePolling` composable，3 秒轮询 `/api/runs/{id}/stages`
- Pipeline 阶段用 Steps 组件 + 进度条
- 当前阶段显示进度百分比和已处理/总数

**LLM 任务队列**：
- 轮询 `/dashboard/api/stats`，展示当前运行中任务数
- 可选：任务列表自动刷新（5 秒间隔）

**未来增强**（不在 Phase 1）：
- WebSocket/SSE 实时推送
- 服务端 events stream

---

## 九、实施节奏

### Phase 1：骨架 + 概览 + Mining 管理（1 周）

| 任务 | 产出 |
|------|------|
| 项目初始化 | Vue 3 + Vite + Element Plus + Router + Pinia + Axios |
| 布局组件 | AppLayout + Sidebar + Header + DomainSelector |
| Domain 管理 | domain store + useDomain composable + domain 配置持久化 |
| CORS 配置 | 三个后端服务添加 CORS |
| API 层 | client.ts + 三个 API 模块 |
| P1 概览页 | 健康状态 + 资产统计 + 最近 runs + 服务状态 |
| P2.1 Runs 列表 | 表格 + 状态过滤 + 操作按钮 |
| P2.2 Run 详情 | Pipeline 时间线 + 文档处理结果 + 自动刷新 |
| 新建 Run | 对话框 + 参数配置 + 提交 |

### Phase 2：检索测试 + 知识资产（1 周）

| 任务 | 产出 |
|------|------|
| P3 检索测试 | 查询输入 + 结果列表 + debug 面板 |
| P4.1 文档列表 | 表格 + 类型过滤 + 搜索 |
| P4.2 文档详情 | 段落/检索单元/关系 Tab |
| P4.3 段落详情展开 | 点击段落显示完整内容 + 关联信息 |

### Phase 3：图谱 + LLM 监控 + 高级特性（1 周）

| 任务 | 产出 |
|------|------|
| P4.4 知识图谱 | AntV G6 力导向图 + 节点交互 + 类型过滤 |
| P5 LLM 监控 | 统计卡片 + 任务列表 + 延迟图表 |
| 监控图表 | Mining 效率趋势 + 检索质量分布 |
| 系统设置 | Domain 管理 + 服务配置 |

---

## 十、与演进路线图的关系

本前端规划是 `docs/2026-05-19-mining-serving-evolution.md` 的配套实施：
- Phase 1 对接当前已有 API（Mining + Serving + LLM）
- Phase 2 随 Mining 演进（实体卡片、操作链等）逐步增加知识资产页面
- Phase 3 随 MCP Tool 扩展增加工具调试页面
- 监控面板随评估体系（Golden Set）建设逐步丰富
