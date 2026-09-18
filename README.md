<div align="center">

# SectorPulse

**Evidence-first A-share sector research and review workspace.**

一个本地优先的 A 股板块研究工作台：从行情与新闻，到板块归因、研究写作和人工审核，保留完整、可回看的证据链。

![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/Web-React-61DAFB?logo=react&logoColor=111827)
![SQLite%20%7C%20PostgreSQL](https://img.shields.io/badge/Database-SQLite%20%7C%20PostgreSQL-4169E1?logo=postgresql&logoColor=white)
![Multi-Agent](https://img.shields.io/badge/Architecture-Multi--Agent-7C3AED?logo=probot&logoColor=white)

</div>

![SectorPulse 运营总览](docs/screenshots/sectorpulse-operations-dashboard.png)

> [!IMPORTANT]
> SectorPulse 是研究与审核工具，不构成投资建议，不自动发布内容，也不执行交易。

## 为什么是 SectorPulse？

SectorPulse 不只生成一篇文章。它会保存行情快照、新闻来源、候选板块、证据归因、草稿版本和人工审核动作，让你能够回看：

- 结论来自哪些数据和来源？
- 哪些证据支持或削弱了这次归因？
- 草稿经过了哪些 Agent 和人工修改？
- 当前结果是否已经通过人工审核？

## 核心能力

- **证据优先**：先采集、核验和归因，再进入写作。
- **父子 Agent 协作**：一个 A0 研究负责人调度 A1–A4 专业 Agent。
- **受控 Skill**：为选题、证据研究、写作和审校提供方法指导。
- **人工把关**：模型不能代替用户选择板块、编辑、批准或撤销。
- **可恢复运行**：任务进度、失败原因、草稿版本和运行状态可追踪。
- **本地优先**：默认 SQLite，也支持 PostgreSQL；Fixture 模式无需联网即可体验。

## 工作方式

```mermaid
flowchart TD
    A[用户发起研究] --> B[A0 研究负责人]
    B -->|委派| C[A1 数据与选题]
    C --> C1[确定性行情/新闻采集 Tool]
    C1 --> C2[质量检查与候选排序 Tool]
    C2 -->|候选提案| D[用户确认范围]
    D -->|确认后返回 A0| B
    B -->|按板块委派| E[A2 板块归因研究]
    E --> E1[确定性新闻与证据 Tool]
    E1 -->|归因产物| B
    B -->|证据齐备后委派| F[A3 编辑写作]
    F -->|大纲/草稿产物| B
    B -->|委派独立审校| G[A4 独立审校]
    G --> H{需要修订?}
    H -->|是：A0 重新委派 A3| F
    H -->|否| I[等待人工审核]
    I --> J[编辑、批准或退回]
```

A0 负责拆解目标和委派任务；A1–A4 负责各自专业阶段。采集、评分、证据校验、预算和数据库操作由受控 Tool 或基础服务执行。

### Agent 角色

| Agent | 负责什么 | 主要产出 |
| --- | --- | --- |
| **A0 研究负责人** | 理解研究目标，安排任务并汇总阶段结果 | 一棵可追踪的研究任务树 |
| **A1 数据与选题** | 编排并调用行情/新闻采集工具，检查数据质量，提出候选板块 | 候选板块提案 |
| **A2 板块归因研究** | 针对每个板块核验新闻和证据，分析上涨或变化原因 | 板块归因分析与证据引用 |
| **A3 编辑写作** | 根据已核验的研究结果组织结构并撰写分析稿 | 大纲、草稿和受控修订稿 |
| **A4 独立审校** | 独立检查事实、来源、证据和表达质量 | 审校意见与通过/修订建议 |

A0 会根据阶段结果继续委派下一步任务；A2 可以按板块并行研究。行情、新闻、评分和质量检查由确定性 Tool/Provider 执行，A1 负责编排调用并解释结果。A4 通过后仍需人工编辑和审核，系统不会自动发布内容。

### 受控 Skill

Skill 是只读的方法库，不是权限系统。当前方法包括：

- `data-gap-handling`、`sector-selection`：数据缺口与板块选题
- `causal-evidence`、`news-verification`：因果证据与新闻核验
- `analysis-writing`：分析写作
- `independent-review`：独立审校

Skill 按角色白名单加载，不能访问任意文件、数据库或审批能力。

### 内部研究资料库（代码已完成，未通过实机验收）

内部研究资料库已作为受控 RAG Tool 接入现有父子 Agent 体系。原始文件、权威状态与审计记录保存在业务存储中，Milvus 只保存可重建的检索索引；A2 负责检索并接纳证据，A3/A4 只使用已形成引用的研究产物。

**当前状态：功能代码已交付并在离线夹具上验证通过，但还没有在任何一台真实机器上跑通过。** 本机没有 PostgreSQL、MinIO、Milvus，也没有配置真实 Provider，因此需要真实服务的验收用例（专用基础设施契约、Provider 冒烟、A0→A4 真实链路）目前只被收集并跳过。跳过不是通过：在按下面的步骤接上真实资源并跑通这些用例之前，请把这一节当作"已实现、未验收"，不要当作可以投产的能力。

已验证的部分（离线，使用夹具 Provider 与内存适配器）：

- 检索质量黄金集 14 项通过，基线为 Recall@12 `1.000`、MRR `0.9167`、nDCG@12 `0.9074`、重复候选比例 `0.0000`，门槛分别是 `0.90 / 0.80 / 0.85 / 0.15`。
- 冲突裁决、摄取、切片、缓存、护栏与 API 的单元与集成用例，包含在整仓回归 `1620 passed, 19 skipped` 里（跳过项全部是"没有配置专用数据库"导致的，与本功能无关）。

未验证的部分：专用 PostgreSQL 契约 75 项、MinIO 10 项、Milvus 21 项、Provider 冒烟 6 项、A0→A4 真实链路 1 项——这些都只有在一台接上了真实资源的机器上才有意义。

```mermaid
flowchart TD
    U[用户上传 PDF / Markdown / TXT] --> I[资料摄取服务]
    I --> P[解析、按需 OCR 与结构化切片]
    P --> S[(原文件与权威元数据)]
    P --> E[Embedding Provider]
    E --> M[(Milvus Dense + BM25 索引)]

    A0[A0 研究负责人] -->|委派| A2[A2 板块归因研究]
    A2 -->|调用受控 Tool| R[内部资料混合检索]
    R --> M
    R --> K[融合与 Rerank]
    K --> F[证据 Artifact 与原文引用]

    subgraph S1[设计如此，尚未接线]
        K -.-> X[相关事实抽取]
        X -.-> N[NLI 冲突检测]
        N -.-> D{规则能否解决冲突?}
        D -.->|是| V[选择有效事实]
        D -.->|否| C[标记未解决冲突]
    end

    V -.-> F
    C -.-> F
    F --> A2
    A2 -->|归因产物返回 A0| A0
    A0 -->|证据齐备后委派| A3[A3 编辑写作]
    A3 -->|草稿返回 A0| A0
    A0 -->|委派审校| A4[A4 独立审校]
```

检索阶段只对当前问题相关的候选事实执行冲突检测。无法根据状态、版本、时间和来源权重解决的冲突必须明确保留，不能由 A3 写成确定性结论。

**虚线框里的那一段目前没有接进运行时。** `ClaimExtractionService`、`ConflictService` 与规则裁决都已实现并各自通过单元测试，但没有任何生产装配会构造它们（`runtime_bundle` 与依赖注入里对 claim / conflict 零引用）。今天在跑的路径是：`conflict_status` 由模型在调用 Tool 时作为必填参数给出，服务端只校验两件窄事——标成 `CHECK_FAILED` 必须带 `requires_verification`，标成 `UNRESOLVED` 必须引用两个不同切片。因此"两条独立等权文档必须停在 UNRESOLVED"这条保证，今天靠的是调用方守规矩，而不是系统拦着。接上真正的裁决链需要先补可用的 Provider 装配（见下面的已知缺口）。

#### 启用与配置

默认关闭。开启需要一组专用资源，全部通过 `.env` 提供：

```dotenv
SECTOR_PULSE_RAG_ENABLED=true
SECTOR_PULSE_RAG_EMBEDDING_DIMENSION=1024        # 必填，且必须与 Milvus 集合的维度一致

SECTOR_PULSE_RAG_MILVUS_URI=http://127.0.0.1:19530
SECTOR_PULSE_RAG_MILVUS_COLLECTION=internal_research_chunks_v1
SECTOR_PULSE_RAG_MILVUS_TOKEN=

SECTOR_PULSE_RAG_MINIO_ENDPOINT=127.0.0.1:9000
SECTOR_PULSE_RAG_MINIO_ACCESS_KEY=...
SECTOR_PULSE_RAG_MINIO_SECRET_KEY=...
SECTOR_PULSE_RAG_MINIO_BUCKET=sectorpulse-research   # 专用且私有；不要与其他业务共用，也不要开匿名读

SECTOR_PULSE_RAG_EMBEDDING_PROVIDER=openai-compatible
SECTOR_PULSE_RAG_EMBEDDING_MODEL=...
SECTOR_PULSE_RAG_RERANKER_PROVIDER=openai-compatible
SECTOR_PULSE_RAG_RERANKER_MODEL=...
SECTOR_PULSE_RAG_NLI_PROVIDER=openai-compatible
SECTOR_PULSE_RAG_NLI_MODEL=...
SECTOR_PULSE_RAG_CLAIM_EXTRACTOR_PROVIDER=openai-compatible
SECTOR_PULSE_RAG_CLAIM_EXTRACTOR_MODEL=...
```

Embedding、Reranker、NLI、Claim Extractor 四类是必配项；OCR 与 Vision 可选，只有页面需要时才被调用，没有它们的部署读不了扫描页（这一点会记进解析警告）。每一类都按自己的前缀单独设置超时、重试与成本闸，例如 Embedding 的 `SECTOR_PULSE_RAG_EMBEDDING_TIMEOUT_SECONDS`、`_MAX_RETRIES`、`_MAX_CALLS_PER_RUN`、`_RESERVE_CNY_PER_CALL`、`_DAILY_BUDGET_CNY`。

**已知缺口：** 每类 RAG Provider 的 base URL 与 API Key 在配置层还没有自己的键。接上真实 Provider 之前需要先补齐这一点——目前没有可用的替代路径。

**Milvus 必须是服务端部署。** 混合检索里的 BM25 全文检索依赖服务端能力，Milvus Lite 不支持，用它启动会在建集合时失败。

#### 使用

开启后，在页面上传 PDF / Markdown / TXT，等摄取完成即可；A2 会在需要时自动检索。资料库的维护面是一组 HTTP 接口：`GET /api/research-library/maintenance` 查看状态，`POST .../maintenance/reconcile` 对账权威库与派生索引，`POST .../maintenance/outbox` 重放索引任务，`POST .../maintenance/purge` 清理过期内容。Milvus 是派生索引，任何时候都可以由权威库重建。

#### 边界

- 单用户部署，没有账号与多租户权限；资料的可见性与权限模型不在当前范围。
- 不自动推断文档版本，版本由上传者显式给出。
- 不支持以图搜图、以文搜图。
- 不自动对外发布任何内容；研究产物仍需人工审核。
- **没有告警。** 指标与对账接口都已就位，但"索引与权威库不一致""摄取租约反复过期""Provider 错误率超阈值""清理失败"这几类状况需要人主动去查，系统不会主动通知。
- 检索包含查询归一化，但**不含查询改写**。
- 换 Embedding 模型需要按新维度建新集合并重建；集合别名的原子切换与回滚窗口尚未实现。
- **冲突裁决链尚未接线**（见上图虚线框）：NLI 检测、确定性裁决与查询期事实抽取都没有生产装配，`RESOLVED` 是否成立由调用方自行申报，服务端不校验。
- **Provider 预算与配额尚未生效**：每类的 `_MAX_CALLS_PER_RUN`、`_RESERVE_CNY_PER_CALL`、`_DAILY_BUDGET_CNY` 与租约都还没有参与决策，`min_ocr_confidence` 也只是一项设置。
- **保留期清理只清权威库的行**：到期后原件仍留在对象存储，而审计记录会写成已清理；对账与派生索引重建可以修复索引，不能修复这一点。
- 派生索引的页边界按一页当全量处理；单个版本的切片数超过一次查询上限时，重复检测会漏报。

## 快速开始

### 环境

- Python 3.12+
- Node.js 22+ 或 24+
- PostgreSQL 16+（可选）

### 安装

```powershell
git clone https://github.com/zrhm666/SectorPulse.git
Set-Location SectorPulse
Copy-Item .env.example .env

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,postgres]"

Set-Location web
npm.cmd ci
npm.cmd run build
Set-Location ..
```

### 启动

```powershell
.\.venv\Scripts\python.exe -m sector_pulse.web.server
```

打开 <http://127.0.0.1:9000>，创建一次 **Fixture 演练**即可开始。Fixture 使用本地样例和临时 SQLite，不访问实时数据，也不消耗真实模型额度。

## 使用真实数据和模型

在 `.env` 中配置 OpenAI-compatible LLM：

```dotenv
SECTOR_PULSE_LLM_PROVIDER=openai-compatible
SECTOR_PULSE_LLM_BASE_URL=https://your-provider.example/v1
SECTOR_PULSE_LLM_API_KEY=your-api-key
SECTOR_PULSE_LLM_MODEL=your-model
```

确认接受外部数据和模型费用后，在仓库根目录创建授权文件：

```powershell
New-Item .live-data-consent -ItemType File -Force
New-Item .live-llm-consent -ItemType File -Force
```

没有授权文件时，系统不会启动相应的外部调用。API Key 只保存在本机 `.env`，不要提交到 Git。

## 数据来源

### 行情与板块

Live 模式默认通过 AkShare 读取 A 股板块行情和板块成分信息，内置支持东方财富和同花顺口径的板块数据适配。Fixture 模式使用本地可复现样例，不访问网络。

### 新闻

新闻来源按 [`config/news_sources.yaml`](config/news_sources.yaml) 管理，当前内置适配包括：

- 财联社（CLS）快讯
- 东方财富新闻
- 巨潮资讯（CNINFO）公告与披露
- 配置化 RSS 来源

系统会记录来源、抓取时间、数据质量和使用的时间边界。新闻原文不可得时会明确标记，不会把缺失内容伪装成已核验事实。

### 可插拔 Provider

行情和新闻都通过统一的 Provider 接口接入。你可以新增自己的数据源适配器，完成字段映射和质量报告后，在运行时 Provider 装配中替换默认实现；上层的候选筛选、证据归因、Agent 和数据库流程无需改动。Provider 也可以通过插件注册机制接入，具体开发约定见 [后端维护指南](backend/README.md)。

## 可插拔组件

SectorPulse 把外部依赖与研究流程分开，替换 Provider 不需要重写 A0–A4 的协作逻辑。

| 组件 | 内置选项 | 适合替换的场景 |
| --- | --- | --- |
| **LLM Provider** | Fixture 模型、OpenAI-compatible 接口 | 切换 DeepSeek、OpenAI 或其他兼容接口；离线演练时使用 Fixture |
| **行情 Provider** | AkShare 东方财富、AkShare 同花顺 | 接入其他行情 API、内部行情服务或自建数据快照 |
| **新闻 Provider** | 财联社、东方财富、巨潮资讯、RSS | 增加行业媒体、公告源、研究机构 RSS 或内部新闻服务 |
| **数据库** | SQLite、PostgreSQL | 单机体验使用 SQLite；长期运行或多人共享时使用 PostgreSQL |
| **资料库模型 Provider** | 任一 OpenAI-compatible 接口（Embedding / Reranker / NLI / 事实提取 / OCR / 视觉） | 换向量模型或换供应商；每类独立配置，互不影响 |
| **派生索引与原件存储** | 当前只内置 Milvus 与 MinIO | 接入已有向量库或对象存储需要自己写适配器（接口已就位，但没有第二个现成实现） |
| **Provider 插件** | 配置化 Provider 注册机制 | 将自定义 Provider 作为独立插件装配，和主程序解耦 |

资料库的三层也各自可替换：模型 Provider 走 `SECTOR_PULSE_RAG_<KIND>_PROVIDER`，向量索引走 `SECTOR_PULSE_RAG_VECTOR_PROVIDER`，原件存储走 `SECTOR_PULSE_RAG_ASSET_PROVIDER`。约束是接口而不是实现：权威状态始终在 PostgreSQL，派生索引任何时候都必须能由它重建。

LLM 只负责研究、写作和审校中的语言推理；行情、新闻和数据库 Provider 必须遵守统一的数据契约，系统会继续执行来源、时间边界、质量和权限校验。这样可以更换数据供应商或模型，而不改变任务树、Skill、人工审核和证据链。

## 数据库

默认使用 SQLite：

```dotenv
SECTOR_PULSE_DATABASE_PATH=data/sector-pulse.db
SECTOR_PULSE_DATABASE_URL=
```

切换 PostgreSQL 时设置：

```dotenv
SECTOR_PULSE_DATABASE_URL=postgresql+psycopg://用户名:密码@127.0.0.1:5432/数据库名
```

应用不会在 PostgreSQL 连接失败时静默回退到 SQLite。

## 项目结构

```text
backend/src/sector_pulse/   后端、编排和业务 Tool
config/prompts/             A0–A4 提示词
config/agent-skills/        受控 Skill 方法库
vendor/aidynamic-agent/      内置 Agent 框架
web/                        React 前端
docs/                       设计与使用文档
```

## 进一步了解

- [产品定义](PRODUCT.md)
- [项目当前状态](docs/PROJECT_STATUS.md)
- [功能迁移说明](docs/superpowers/specs/2026-09-13-feature-migration-map.md)
- [多 Agent 架构设计](docs/superpowers/specs/2026-09-12-multi-agent-platform-design.md)
- [后端维护指南](backend/README.md)

## License

本项目采用 [MIT License](LICENSE)。
